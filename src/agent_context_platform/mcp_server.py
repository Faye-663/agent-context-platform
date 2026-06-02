from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, Literal, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

McpTransport = Literal["stdio", "streamable-http"]
_VALID_MCP_TRANSPORTS = {"stdio", "streamable-http"}


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


@dataclass(frozen=True)
class JsonHttpResponse:
    """Context API HTTP 响应的最小抽象，便于测试替换 urllib 实现。"""

    # status_code 保留 HTTP 状态码，例如 200 或 400。
    status_code: int
    # payload 是已经解码后的 JSON dict。
    payload: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self.payload


class ContextApiHttpClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0):
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
    def __init__(self, http_client: HttpClient):
        self.http_client = http_client

    def search_code(
        self,
        *,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        query_embedding: list[float] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._post_search(
            "/search-code",
            query=query,
            limit=limit,
            filters=filters,
            query_embedding=query_embedding,
            request_id=request_id,
        )

    def search_db_schema(
        self,
        *,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        query_embedding: list[float] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._post_search(
            "/search-db-schema",
            query=query,
            limit=limit,
            filters=filters,
            query_embedding=query_embedding,
            request_id=request_id,
        )

    def search_doc(
        self,
        *,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        query_embedding: list[float] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._post_search(
            "/search-doc",
            query=query,
            limit=limit,
            filters=filters,
            query_embedding=query_embedding,
            request_id=request_id,
        )

    def build_task_context(
        self,
        *,
        task: str,
        limits: dict[str, int] | None = None,
        constraints: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task": task,
            "limits": limits or {},
            "constraints": constraints or {},
        }
        if request_id is not None:
            payload["request_id"] = request_id
        return self._post("/build-task-context", payload)

    def _post_search(
        self,
        path: str,
        *,
        query: str,
        limit: int,
        filters: dict[str, Any] | None,
        query_embedding: list[float] | None,
        request_id: str | None,
    ) -> dict[str, Any]:
        # search_* 工具共享同一 payload 形状，便于 Agent 在不同资产类型之间切换。
        payload: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "filters": filters or {},
        }
        if query_embedding is not None:
            payload["query_embedding"] = query_embedding
        if request_id is not None:
            payload["request_id"] = request_id
        return self._post(path, payload)

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
    tool_client = ContextApiToolClient(http_client or ContextApiHttpClient(base_url))

    @server.tool()
    def search_code(
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        query_embedding: list[float] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Search indexed Java code through Context API."""
        return tool_client.search_code(
            query=query,
            limit=limit,
            filters=filters,
            query_embedding=query_embedding,
            request_id=request_id,
        )

    @server.tool()
    def search_db_schema(
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        query_embedding: list[float] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Search indexed SQL schema through Context API."""
        return tool_client.search_db_schema(
            query=query,
            limit=limit,
            filters=filters,
            query_embedding=query_embedding,
            request_id=request_id,
        )

    @server.tool()
    def search_doc(
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        query_embedding: list[float] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Search indexed Markdown docs through Context API."""
        return tool_client.search_doc(
            query=query,
            limit=limit,
            filters=filters,
            query_embedding=query_embedding,
            request_id=request_id,
        )

    @server.tool()
    def build_task_context(
        task: str,
        limits: dict[str, int] | None = None,
        constraints: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Build task context through Context API."""
        return tool_client.build_task_context(
            task=task,
            limits=limits,
            constraints=constraints,
            request_id=request_id,
        )

    return server


def main() -> None:
    settings = load_mcp_server_settings()
    server = create_mcp_server(
        base_url=settings.context_api_base_url,
        host=settings.host,
        port=settings.port,
        path=settings.path,
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
