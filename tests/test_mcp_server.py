from __future__ import annotations

import asyncio

import pytest

from agent_context_platform.mcp_server import (
    ContextApiError,
    ContextApiToolClient,
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


def test_load_mcp_server_settings_defaults_to_stdio() -> None:
    settings = load_mcp_server_settings({})

    assert settings.context_api_base_url == "http://127.0.0.1:8000"
    assert settings.transport == "stdio"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8001
    assert settings.path == "/mcp"


def test_load_mcp_server_settings_reads_streamable_http_values() -> None:
    settings = load_mcp_server_settings(
        {
            "ACP_CONTEXT_API_BASE_URL": "https://context-api.example.com",
            "ACP_MCP_TRANSPORT": "streamable-http",
            "ACP_MCP_HOST": "0.0.0.0",
            "ACP_MCP_PORT": "9001",
            "ACP_MCP_PATH": "/agent-context",
        }
    )

    assert settings.context_api_base_url == "https://context-api.example.com"
    assert settings.transport == "streamable-http"
    assert settings.host == "0.0.0.0"
    assert settings.port == 9001
    assert settings.path == "/agent-context"


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
