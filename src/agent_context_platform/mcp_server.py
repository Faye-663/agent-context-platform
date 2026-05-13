from __future__ import annotations

import json
import os
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, Any]:
        ...


class HttpClient(Protocol):
    def post(self, path: str, json: dict[str, Any]) -> HttpResponse:
        ...


class ContextApiError(RuntimeError):
    def __init__(
        self, code: str, message: str, details: Any | None = None
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class JsonHttpResponse:
    status_code: int
    payload: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self.payload


class ContextApiHttpClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def post(self, path: str, json: dict[str, Any]) -> JsonHttpResponse:
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
):
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("agent-context-platform", json_response=True)
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
    base_url = os.environ.get("ACP_CONTEXT_API_BASE_URL", "http://127.0.0.1:8000")
    server = create_mcp_server(base_url=base_url)
    server.run()


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
