from __future__ import annotations

import asyncio

import pytest

from agent_context_platform.mcp_server import (
    ContextApiError,
    ContextApiToolClient,
    create_mcp_server,
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
