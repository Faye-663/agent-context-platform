from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

McpTransport = Literal["stdio", "streamable-http"]
_VALID_MCP_TRANSPORTS = {"stdio", "streamable-http"}
logger = logging.getLogger(__name__)


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, Any]:
        ...


class HttpClient(Protocol):
    def post(self, path: str, json: dict[str, Any]) -> HttpResponse:
        ...


class ContextApiError(RuntimeError):
    """MCP 工具调用 Context API 失败时抛出的错误。

    例子：code="embedding_unavailable" 表示向量 provider 或维度校验失败。
    """

    def __init__(
        self, code: str, message: str, details: Any | None = None
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details


class McpServerConfigError(ValueError):
    """MCP server 启动配置错误。"""


@dataclass(frozen=True)
class McpServerSettings:
    """`acp-mcp-server` 的启动配置。

    `context_api_base_url` 是 MCP wrapper 调用 Context API 的地址，不是 Agent 侧 MCP URL。
    """

    context_api_base_url: str
    transport: McpTransport
    host: str
    port: int
    path: str
    log_file: str | None
    log_payloads: bool


@dataclass(frozen=True)
class JsonHttpResponse:
    """Context API HTTP 响应的最小抽象，便于测试替换 urllib 实现。"""

    # status_code 保留 HTTP 状态码，例如 200 或 400。
    status_code: int
    # payload 是已经解码后的 JSON dict。
    payload: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self.payload


class McpTraceLogger:
    """把 MCP tool 调用写成 JSONL，供调试和评测复盘。

    日志写入失败只影响观测能力，不应改变一次成功的 MCP tool 调用结果。
    """

    def __init__(self, *, log_file: str | Path, include_payloads: bool = False) -> None:
        self.log_file = Path(log_file)
        self.include_payloads = include_payloads

    def trace(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        call: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        mcp_call_id = str(uuid4())
        started = time.perf_counter()
        try:
            response = call()
        except ContextApiError as exc:
            self._write_event(
                _build_error_event(
                    tool=tool,
                    arguments=arguments,
                    mcp_call_id=mcp_call_id,
                    elapsed_ms=_elapsed_ms(started),
                    exc=exc,
                    include_payloads=self.include_payloads,
                )
            )
            raise
        except Exception as exc:
            self._write_event(
                _build_unhandled_error_event(
                    tool=tool,
                    arguments=arguments,
                    mcp_call_id=mcp_call_id,
                    elapsed_ms=_elapsed_ms(started),
                    exc=exc,
                    include_payloads=self.include_payloads,
                )
            )
            raise

        self._write_event(
            _build_success_event(
                tool=tool,
                arguments=arguments,
                mcp_call_id=mcp_call_id,
                elapsed_ms=_elapsed_ms(started),
                response=response,
                include_payloads=self.include_payloads,
            )
        )
        return response

    def _write_event(self, event: dict[str, Any]) -> None:
        try:
            with self.log_file.open("a", encoding="utf-8", newline="\n") as log:
                log.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
                log.write("\n")
        except OSError:
            logger.exception("mcp_trace_log_write_failed path=%s", self.log_file)


class ContextApiHttpClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 60.0):
        # base_url 指向 Context API，例如 "http://127.0.0.1:8000"。
        self.base_url = base_url.rstrip("/")
        # timeout_seconds 防止 MCP 工具调用无限等待后端 API。
        self.timeout_seconds = timeout_seconds

    def post(self, path: str, json: dict[str, Any]) -> JsonHttpResponse:
        # MCP 进程不直连数据库，而是通过 Context API 复用同一套校验、检索和错误处理。
        url = f"{self.base_url}/{path.lstrip('/')}"
        data = _json_bytes(json)
        request = Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return JsonHttpResponse(
                    status_code=response.status,
                    payload=_decode_json(response.read()),
                )
        except HTTPError as exc:
            return JsonHttpResponse(
                status_code=exc.code,
                payload=_decode_json(exc.read()),
            )
        except URLError as exc:
            raise ContextApiError("context_api_unreachable", str(exc.reason)) from exc


class ContextApiToolClient:
    def __init__(
        self,
        http_client: HttpClient,
        *,
        trace_logger: McpTraceLogger | None = None,
    ):
        self.http_client = http_client
        self.trace_logger = trace_logger

    def search_code(
        self,
        *,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        debug_options: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._post_search(
            "search_code",
            "/search-code",
            query=query,
            limit=limit,
            filters=filters,
            debug_options=debug_options,
            request_id=request_id,
        )

    def search_db_schema(
        self,
        *,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        debug_options: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._post_search(
            "search_db_schema",
            "/search-db-schema",
            query=query,
            limit=limit,
            filters=filters,
            debug_options=debug_options,
            request_id=request_id,
        )

    def search_doc(
        self,
        *,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        debug_options: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._post_search(
            "search_doc",
            "/search-doc",
            query=query,
            limit=limit,
            filters=filters,
            debug_options=debug_options,
            request_id=request_id,
        )

    def build_task_context(
        self,
        *,
        task: str,
        limits: dict[str, int] | None = None,
        constraints: dict[str, Any] | None = None,
        debug_options: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task": task,
            "limits": limits or {},
            "constraints": constraints or {},
        }
        if debug_options is not None:
            payload["debug_options"] = debug_options
        if request_id is not None:
            payload["request_id"] = request_id
        return self._post_tool("build_task_context", "/build-task-context", payload)

    def _post_search(
        self,
        tool: str,
        path: str,
        *,
        query: str,
        limit: int,
        filters: dict[str, Any] | None,
        debug_options: dict[str, Any] | None,
        request_id: str | None,
    ) -> dict[str, Any]:
        # search_* 工具共享同一 payload 形状，便于 Agent 在不同资产类型之间切换。
        payload: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "filters": filters or {},
        }
        if debug_options is not None:
            payload["debug_options"] = debug_options
        if request_id is not None:
            payload["request_id"] = request_id
        return self._post_tool(tool, path, payload)

    def _post_tool(
        self, tool: str, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if self.trace_logger is None:
            return self._post(path, payload)
        return self.trace_logger.trace(
            tool=tool,
            arguments=payload,
            call=lambda: self._post(path, payload),
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.http_client.post(path, json=payload)
        body = response.json()
        if response.status_code >= 400:
            # 保留 Context API 的错误码和 details，MCP 调试时才能定位是参数、embedding 还是存储问题。
            error = body.get("error", {})
            if isinstance(error, dict):
                code = str(error.get("code") or "context_api_error")
                message = str(error.get("message") or "Context API request failed.")
                raise ContextApiError(code, message, error.get("details"))
            raise ContextApiError("context_api_error", "Context API request failed.")
        return body


def create_mcp_server(
    *,
    base_url: str = "http://127.0.0.1:8000",
    http_client: HttpClient | None = None,
    host: str = "127.0.0.1",
    port: int = 8001,
    path: str = "/mcp",
    trace_logger: McpTraceLogger | None = None,
):
    from mcp.server.fastmcp import FastMCP

    # FastMCP 只暴露工具壳；业务逻辑仍在 Context API，避免 MCP 和 HTTP 两套行为漂移。
    server = FastMCP(
        "agent-context-platform",
        host=host,
        port=port,
        streamable_http_path=path,
        json_response=True,
    )
    tool_client = ContextApiToolClient(
        http_client or ContextApiHttpClient(base_url),
        trace_logger=trace_logger,
    )

    @server.tool()
    def search_code(
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        debug_options: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """通过 Context API 检索已索引的 Java code。

        适用场景：在任务目标已基本明确后，精确查找 Java class、method、
        调用模式、错误处理逻辑或相似实现。
        不适用：实时读取文件、检索非 Java 资产、写数据库，或在项目尚未索引时
        把结果当成完整工程事实。
        输入建议：`query` 使用具体功能、symbol、错误、行为或实现模式；仅当任务
        已明确范围时才用 `filters` 限定 `repo`、`language`、`symbol_type`
        或 `path_prefix`；
        follow-up 检索时保持较小 `limit`。
        输出使用：基于返回的 source citation、`match_reason` 和 score 判断结果是否
        足够相关，再引用或采纳。
        兜底策略：如果结果为空或相关性弱，先调用 `build_task_context` 获取更宽的
        task context，或改用其他 `search_*` 工具；不要凭空补全缺失上下文。
        """
        return tool_client.search_code(
            query=query,
            limit=limit,
            filters=filters,
            debug_options=debug_options,
            request_id=request_id,
        )

    @server.tool()
    def search_db_schema(
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        debug_options: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """通过 Context API 检索已索引的 SQL schema。

        适用场景：需要表、字段、状态值、约束、数据关系或业务数据模型上下文。
        不适用：执行 SQL、修改数据、实时检查数据库，或检索 code / Markdown docs。
        输入建议：`query` 使用业务实体、表含义、字段名、状态值或数据关系；仅当
        已知表名或路径范围时才用 `filters` 限定 `table` 或 `path_prefix`。
        输出使用：基于 table / column source citation 和 `match_reason` 支撑 schema
        相关判断或迁移影响分析。
        兜底策略：如果 schema 上下文缺失，调用 `build_task_context` 或 `search_doc`
        查设计意图；把 `missing_context` 视为不确定性，而不是证据。
        """
        return tool_client.search_db_schema(
            query=query,
            limit=limit,
            filters=filters,
            debug_options=debug_options,
            request_id=request_id,
        )

    @server.tool()
    def search_doc(
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        debug_options: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """通过 Context API 检索已索引的 Markdown docs。

        适用场景：需要需求、设计说明、ADR、验证记录、rollout notes 或 API docs。
        不适用：查源码、查 SQL schema、实时读取文件，或把旧文档直接当成当前行为。
        输入建议：`query` 使用功能、决策、API、风险或验证主题；仅当已知文档区域
        时才用 `filters` 限定 `path_prefix`。
        输出使用：基于 path、`heading_path`、line citation 和 `match_reason` 区分长期
        决策、背景材料和可能过期的信息。
        兜底策略：如果文档缺失或疑似过期，调用 `build_task_context` 或相关
        `search_*` 工具交叉确认，并明确暴露文档缺口。
        """
        return tool_client.search_doc(
            query=query,
            limit=limit,
            filters=filters,
            debug_options=debug_options,
            request_id=request_id,
        )

    @server.tool()
    def build_task_context(
        task: str,
        limits: dict[str, int] | None = None,
        constraints: dict[str, Any] | None = None,
        debug_options: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """通过 Context API 构建 task context。

        适用场景：这是默认优先入口；在改代码前、规划实现、排查行为或回答需要
        工程上下文的问题时，先用它聚合 code、SQL schema、docs 和相似实现。
        不适用：泛聊天、实时读取文件、索引新内容、写数据，或替代用户对模糊需求
        的确认。
        输入建议：`task` 写用户的具体工程目标；用 `limits` 控制 code、db_schema、
        docs、similar_implementations 数量；`constraints` 只填写已知事实，例如
        language 或 path scope。
        输出使用：把返回值作为 task context package；结论必须基于 `related_*`、
        `risks`、`missing_context` 和 `citations`。
        兜底策略：如果 `missing_context` 非空或 citation 较弱，不要制造确定性；
        继续调用 `search_code`、`search_db_schema`、`search_doc`，本地检查，或提问。
        """
        return tool_client.build_task_context(
            task=task,
            limits=limits,
            constraints=constraints,
            debug_options=debug_options,
            request_id=request_id,
        )

    return server


def main() -> None:
    settings = load_mcp_server_settings()
    trace_logger = (
        McpTraceLogger(
            log_file=settings.log_file,
            include_payloads=settings.log_payloads,
        )
        if settings.log_file is not None
        else None
    )
    server = create_mcp_server(
        base_url=settings.context_api_base_url,
        host=settings.host,
        port=settings.port,
        path=settings.path,
        trace_logger=trace_logger,
    )
    server.run(transport=settings.transport)


def load_mcp_server_settings(
    environ: Mapping[str, str] | None = None,
) -> McpServerSettings:
    values = dict(os.environ if environ is None else environ)
    transport = values.get("ACP_MCP_TRANSPORT", "stdio").strip()
    if transport not in _VALID_MCP_TRANSPORTS:
        raise McpServerConfigError(
            "ACP_MCP_TRANSPORT 只支持 stdio 或 streamable-http。"
        )

    return McpServerSettings(
        context_api_base_url=values.get(
            "ACP_CONTEXT_API_BASE_URL", "http://127.0.0.1:8000"
        ).strip(),
        transport=cast(McpTransport, transport),
        host=values.get("ACP_MCP_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_parse_mcp_port(values.get("ACP_MCP_PORT", "8001")),
        path=_parse_mcp_path(values.get("ACP_MCP_PATH", "/mcp")),
        log_file=_parse_mcp_log_file(values.get("ACP_MCP_LOG_FILE")),
        log_payloads=_parse_bool(
            values.get("ACP_MCP_LOG_PAYLOADS", "false"),
            "ACP_MCP_LOG_PAYLOADS",
        ),
    )


def _parse_mcp_port(value: str | None) -> int:
    raw_value = (value or "").strip()
    try:
        port = int(raw_value)
    except ValueError as exc:
        raise McpServerConfigError("ACP_MCP_PORT 必须是 1 到 65535 的整数。") from exc
    if port < 1 or port > 65535:
        raise McpServerConfigError("ACP_MCP_PORT 必须是 1 到 65535 的整数。")
    return port


def _parse_mcp_path(value: str | None) -> str:
    path = (value or "").strip()
    if not path or not path.startswith("/"):
        raise McpServerConfigError("ACP_MCP_PATH 必须以 / 开头。")
    return path


def _parse_mcp_log_file(value: str | None) -> str | None:
    path = (value or "").strip()
    if not path:
        return None
    log_path = Path(path)
    parent = log_path.parent
    if parent != Path(".") and not parent.exists():
        raise McpServerConfigError("ACP_MCP_LOG_FILE 的父目录必须存在。")
    if parent != Path(".") and not parent.is_dir():
        raise McpServerConfigError("ACP_MCP_LOG_FILE 的父路径必须是目录。")
    return path


def _parse_bool(value: str | None, name: str) -> bool:
    normalized = (value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise McpServerConfigError(f"{name} 必须是 true/false 类型值。")


def _build_success_event(
    *,
    tool: str,
    arguments: dict[str, Any],
    mcp_call_id: str,
    elapsed_ms: float,
    response: dict[str, Any],
    include_payloads: bool,
) -> dict[str, Any]:
    event = _base_trace_event(
        tool=tool,
        arguments=arguments,
        mcp_call_id=mcp_call_id,
        elapsed_ms=elapsed_ms,
        status="ok",
    )
    event["summary"] = _summarize_response(response)
    if include_payloads:
        event["payload"] = {"arguments": arguments, "response": response}
    return event


def _build_error_event(
    *,
    tool: str,
    arguments: dict[str, Any],
    mcp_call_id: str,
    elapsed_ms: float,
    exc: ContextApiError,
    include_payloads: bool,
) -> dict[str, Any]:
    event = _base_trace_event(
        tool=tool,
        arguments=arguments,
        mcp_call_id=mcp_call_id,
        elapsed_ms=elapsed_ms,
        status="error",
    )
    event["summary"] = {"error_code": exc.code, "error_message": exc.message}
    if include_payloads:
        error: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            error["details"] = exc.details
        event["payload"] = {"arguments": arguments, "error": error}
    return event


def _build_unhandled_error_event(
    *,
    tool: str,
    arguments: dict[str, Any],
    mcp_call_id: str,
    elapsed_ms: float,
    exc: Exception,
    include_payloads: bool,
) -> dict[str, Any]:
    event = _base_trace_event(
        tool=tool,
        arguments=arguments,
        mcp_call_id=mcp_call_id,
        elapsed_ms=elapsed_ms,
        status="error",
    )
    event["summary"] = {
        "error_code": type(exc).__name__,
        "error_message": str(exc),
    }
    if include_payloads:
        event["payload"] = {
            "arguments": arguments,
            "error": {
                "code": type(exc).__name__,
                "message": str(exc),
            },
        }
    return event


def _base_trace_event(
    *,
    tool: str,
    arguments: dict[str, Any],
    mcp_call_id: str,
    elapsed_ms: float,
    status: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "event": "mcp_tool_call",
        "mcp_call_id": mcp_call_id,
        "tool": tool,
        "request_id": _request_id_from(arguments),
        "status": status,
        "elapsed_ms": elapsed_ms,
    }


def _request_id_from(arguments: dict[str, Any]) -> str | None:
    request_id = arguments.get("request_id")
    if request_id is None:
        return None
    return str(request_id)


def _summarize_response(response: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"response_keys": sorted(response.keys())}
    results = response.get("results")
    if isinstance(results, list):
        summary["result_count"] = len(results)
        return summary
    citations = response.get("citations")
    if isinstance(citations, list):
        summary["result_count"] = len(citations)
    return summary


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _decode_json(data: bytes) -> dict[str, Any]:
    if not data:
        return {}
    text = data.decode("utf-8")
    try:
        decoded = json.loads(text)
    except JSONDecodeError:
        return {
            "error": {
                "code": "context_api_error",
                "message": text or "Context API returned a non-JSON response.",
            }
        }
    if isinstance(decoded, dict):
        return decoded
    return {"value": decoded}


if __name__ == "__main__":
    main()
