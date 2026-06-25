from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agent_context_platform import mcp_server
from agent_context_platform.mcp_server import (
    ContextApiError,
    ContextApiHttpClient,
    ContextApiToolClient,
    McpTraceLogger,
    McpServerConfigError,
    create_mcp_server,
    load_mcp_server_settings,
    _decode_json,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, path: str, json: dict[str, object]) -> FakeResponse:
        self.calls.append((path, json))
        return self.response


class FakeUrlopenResponse:
    status = 200

    def __enter__(self) -> "FakeUrlopenResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"results": []}'


def test_load_mcp_server_settings_defaults_to_stdio() -> None:
    settings = load_mcp_server_settings({})

    assert settings.context_api_base_url == "http://127.0.0.1:8000"
    assert settings.transport == "stdio"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8001
    assert settings.path == "/mcp"
    assert settings.log_file is None
    assert settings.log_payloads is False


def test_load_mcp_server_settings_reads_streamable_http_and_log_values(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "mcp-debug.jsonl"
    settings = load_mcp_server_settings(
        {
            "ACP_CONTEXT_API_BASE_URL": "https://context-api.example.com",
            "ACP_MCP_TRANSPORT": "streamable-http",
            "ACP_MCP_HOST": "0.0.0.0",
            "ACP_MCP_PORT": "9001",
            "ACP_MCP_PATH": "/agent-context",
            "ACP_MCP_LOG_FILE": str(log_file),
            "ACP_MCP_LOG_PAYLOADS": "true",
        }
    )

    assert settings.context_api_base_url == "https://context-api.example.com"
    assert settings.transport == "streamable-http"
    assert settings.host == "0.0.0.0"
    assert settings.port == 9001
    assert settings.path == "/agent-context"
    assert settings.log_file == str(log_file)
    assert settings.log_payloads is True


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"ACP_MCP_TRANSPORT": "sse"}, "ACP_MCP_TRANSPORT"),
        ({"ACP_MCP_TRANSPORT": "websocket"}, "ACP_MCP_TRANSPORT"),
        ({"ACP_MCP_PORT": "not-a-number"}, "ACP_MCP_PORT"),
        ({"ACP_MCP_PORT": "0"}, "ACP_MCP_PORT"),
        ({"ACP_MCP_PORT": "65536"}, "ACP_MCP_PORT"),
        ({"ACP_MCP_PATH": ""}, "ACP_MCP_PATH"),
        ({"ACP_MCP_PATH": "mcp"}, "ACP_MCP_PATH"),
        ({"ACP_MCP_LOG_PAYLOADS": "sometimes"}, "ACP_MCP_LOG_PAYLOADS"),
        (
            {"ACP_MCP_LOG_FILE": "missing-parent/mcp.jsonl"},
            "ACP_MCP_LOG_FILE",
        ),
    ],
)
def test_load_mcp_server_settings_rejects_invalid_values(
    environ: dict[str, str], message: str
) -> None:
    with pytest.raises(McpServerConfigError, match=message):
        load_mcp_server_settings(environ)


def test_create_mcp_server_configures_streamable_http_endpoint() -> None:
    server = create_mcp_server(
        http_client=FakeHttpClient(FakeResponse(200, {})),
        host="0.0.0.0",
        port=9001,
        path="/agent-context",
    )

    assert server.settings.host == "0.0.0.0"
    assert server.settings.port == 9001
    assert server.settings.streamable_http_path == "/agent-context"


def test_context_api_http_client_allows_real_project_retrieval_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, float] = {}

    def fake_urlopen(_request: object, *, timeout: float) -> FakeUrlopenResponse:
        observed["timeout"] = timeout
        return FakeUrlopenResponse()

    monkeypatch.setattr(mcp_server, "urlopen", fake_urlopen)

    response = ContextApiHttpClient("http://context-api.example.com").post(
        "/search-code", {"query": "CampusController"}
    )

    assert response.status_code == 200
    assert response.json() == {"results": []}
    assert observed["timeout"] == 60.0


def test_build_task_context_tool_posts_http_contract_payload() -> None:
    response = FakeResponse(
        200,
        {
            "query": "新增支付接口",
            "related_code": [],
            "related_db_schema": [],
            "related_docs": [],
            "similar_implementations": [],
            "risks": ["未召回到 code 上下文，需要人工确认。"],
            "missing_context": ["code"],
            "citations": [],
        },
    )
    http_client = FakeHttpClient(response)
    tool_client = ContextApiToolClient(http_client)

    result = tool_client.build_task_context(
        task="新增支付接口",
        limits={"code": 5},
        constraints={"language": "java"},
        request_id="req-mcp-1",
    )

    assert result["query"] == "新增支付接口"
    assert http_client.calls == [
        (
            "/build-task-context",
            {
                "task": "新增支付接口",
                "limits": {"code": 5},
                "constraints": {"language": "java"},
                "request_id": "req-mcp-1",
            },
        )
    ]


def test_build_task_context_tool_raises_agent_readable_context_api_error() -> None:
    response = FakeResponse(
        400,
        {"error": {"code": "invalid_request", "message": "task must not be empty"}},
    )
    tool_client = ContextApiToolClient(FakeHttpClient(response))

    with pytest.raises(ContextApiError, match="invalid_request: task must not be empty"):
        tool_client.build_task_context(task="")


def test_mcp_trace_logger_does_not_create_log_when_disabled(tmp_path: Path) -> None:
    log_file = tmp_path / "mcp-debug.jsonl"
    tool_client = ContextApiToolClient(
        FakeHttpClient(FakeResponse(200, {"results": []}))
    )

    result = tool_client.search_code(query="payment", request_id="req-1")

    assert result == {"results": []}
    assert not log_file.exists()


def test_mcp_trace_logger_records_summary_without_payload(tmp_path: Path) -> None:
    log_file = tmp_path / "mcp-debug.jsonl"
    tool_client = ContextApiToolClient(
        FakeHttpClient(FakeResponse(200, {"results": [{"title": "Payment"}]})),
        trace_logger=McpTraceLogger(log_file=log_file, include_payloads=False),
    )

    tool_client.search_code(
        query="payment",
        filters={"language": "java"},
        request_id="req-2",
    )

    event = _read_single_jsonl_event(log_file)
    assert event["schema_version"] == 1
    assert event["event"] == "mcp_tool_call"
    assert event["tool"] == "search_code"
    assert event["request_id"] == "req-2"
    assert event["status"] == "ok"
    assert event["elapsed_ms"] >= 0
    assert event["mcp_call_id"]
    assert event["summary"] == {
        "result_count": 1,
        "response_keys": ["results"],
    }
    assert "timestamp" in event
    assert "payload" not in event


def test_mcp_trace_logger_records_full_payload_when_enabled(tmp_path: Path) -> None:
    log_file = tmp_path / "mcp-debug.jsonl"
    response_payload = {"results": [{"title": "Payment"}]}
    tool_client = ContextApiToolClient(
        FakeHttpClient(FakeResponse(200, response_payload)),
        trace_logger=McpTraceLogger(log_file=log_file, include_payloads=True),
    )

    tool_client.search_doc(
        query="payment design",
        limit=3,
        filters={"path_prefix": "docs"},
        request_id="req-3",
    )

    event = _read_single_jsonl_event(log_file)
    assert event["summary"]["result_count"] == 1
    assert event["payload"] == {
        "arguments": {
            "query": "payment design",
            "limit": 3,
            "filters": {"path_prefix": "docs"},
            "request_id": "req-3",
        },
        "response": response_payload,
    }


def test_mcp_trace_logger_records_context_api_error(tmp_path: Path) -> None:
    log_file = tmp_path / "mcp-debug.jsonl"
    error_payload = {
        "error": {
            "code": "invalid_request",
            "message": "task must not be empty",
            "details": {"field": "task"},
        }
    }
    tool_client = ContextApiToolClient(
        FakeHttpClient(FakeResponse(400, error_payload)),
        trace_logger=McpTraceLogger(log_file=log_file, include_payloads=True),
    )

    with pytest.raises(ContextApiError, match="invalid_request: task must not be empty"):
        tool_client.build_task_context(task="", request_id="req-4")

    event = _read_single_jsonl_event(log_file)
    assert event["tool"] == "build_task_context"
    assert event["request_id"] == "req-4"
    assert event["status"] == "error"
    assert event["summary"] == {
        "error_code": "invalid_request",
        "error_message": "task must not be empty",
    }
    assert event["payload"] == {
        "arguments": {
            "task": "",
            "limits": {},
            "constraints": {},
            "request_id": "req-4",
        },
        "error": {
            "code": "invalid_request",
            "message": "task must not be empty",
            "details": {"field": "task"},
        },
    }


def test_non_json_context_api_error_becomes_agent_readable_error() -> None:
    assert _decode_json(b"service unavailable") == {
        "error": {
            "code": "context_api_error",
            "message": "service unavailable",
        }
    }


def test_mcp_server_registers_tools_and_calls_context_api() -> None:
    response = FakeResponse(
        200,
        {
            "query": "新增支付接口",
            "related_code": [],
            "related_db_schema": [],
            "related_docs": [],
            "similar_implementations": [],
            "risks": [],
            "missing_context": [],
            "citations": [],
        },
    )
    http_client = FakeHttpClient(response)
    server = create_mcp_server(http_client=http_client)

    async def call_tool() -> None:
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == {
            "search_code",
            "search_db_schema",
            "search_doc",
            "build_task_context",
        }

        result = await server.call_tool(
            "build_task_context", {"task": "新增支付接口"}
        )

        assert result[1]["query"] == "新增支付接口"

    asyncio.run(call_tool())
    assert http_client.calls == [
        (
            "/build-task-context",
            {
                "task": "新增支付接口",
                "limits": {},
                "constraints": {},
            },
        )
    ]


def test_mcp_tool_descriptions_guide_agent_tool_selection() -> None:
    server = create_mcp_server(http_client=FakeHttpClient(FakeResponse(200, {})))

    async def list_tool_descriptions() -> dict[str, str]:
        tools = await server.list_tools()
        return {tool.name: tool.description or "" for tool in tools}

    descriptions = asyncio.run(list_tool_descriptions())

    for tool_name, description in descriptions.items():
        assert "适用场景" in description, tool_name
        assert "不适用" in description, tool_name
        assert "输入建议" in description, tool_name
        assert "输出使用" in description, tool_name
        assert "兜底策略" in description, tool_name

    build_task_context = descriptions["build_task_context"]
    assert "默认优先入口" in build_task_context
    assert "改代码前" in build_task_context
    assert "task context" in build_task_context

    assert "Java code" in descriptions["search_code"]
    assert "SQL schema" in descriptions["search_db_schema"]
    assert "Markdown docs" in descriptions["search_doc"]


def _read_single_jsonl_event(log_file: Path) -> dict[str, object]:
    events = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 1
    return events[0]
