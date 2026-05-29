from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from agent_context_platform.context_builder import TaskContextBuilder
from agent_context_platform.embeddings import (
    EmbeddingDimensionError,
    EmbeddingProviderError,
)
from agent_context_platform.models import AssetType, SearchResult
from agent_context_platform.retrieval import HybridSearchQuery, HybridSearchService


logger = logging.getLogger(__name__)
SearchServiceScope = Callable[[], AbstractContextManager[HybridSearchService]]


class SearchFilters(BaseModel):
    """搜索接口的结构化过滤条件。

    例子：{"language": "java", "symbol_type": ["method"], "path_prefix": "src/main/java"}。
    """

    # language 主要用于代码资产，例如 "java"。
    language: str | None = None
    # symbol_type 可筛选 class/method/table/column 等索引器写入的类型。
    symbol_type: str | list[str] | None = None
    # path_prefix 用于限制仓库子目录，例如只搜 "docs/" 或 "src/main/java/"。
    path_prefix: str | None = None
    # table 用于 DB schema 搜索，例如 "payment_order"。
    table: str | None = None


class SearchRequest(BaseModel):
    """三个 search endpoint 共用的请求体。

    /search-code、/search-db-schema、/search-doc 只在 asset_type 上不同。
    """

    # query 是用户自然语言问题或关键词。
    query: str = Field(min_length=1)
    # limit 限制单次返回数量，防止 Agent 一次拉太多上下文。
    limit: int = Field(default=10, ge=1, le=50)
    # filters 是可选结构化过滤条件，不传时使用空过滤。
    filters: SearchFilters = Field(default_factory=SearchFilters)
    # query_embedding 用于绕过 provider 直接传查询向量，常见于测试或上游已生成向量的场景。
    query_embedding: list[float] | None = None
    # request_id 贯穿日志，便于排查一次 Agent 调用链路。
    request_id: str | None = None


class BuildTaskContextRequest(BaseModel):
    """build-task-context 的请求体。

    例子：task="修改支付报文生成逻辑"，constraints={"language": "java"}。
    """

    # task 是要交给 Agent 执行的任务描述，也是多路检索的查询文本。
    task: str = Field(min_length=1)
    # limits 可分别控制 code/db_schema/docs/similar_implementations 的返回数量。
    limits: dict[str, int] = Field(default_factory=dict)
    # constraints 当前主要用于 language 等跨检索类型约束。
    constraints: dict[str, Any] = Field(default_factory=dict)
    # request_id 用于日志追踪；不传时 API 会自动生成。
    request_id: str | None = None


def create_app(
    search_service: HybridSearchService | None = None,
    *,
    search_service_scope: SearchServiceScope | None = None,
) -> FastAPI:
    # 测试可传单例 search_service；真实运行用 scope 为每次请求创建/关闭数据库会话。
    if search_service is None and search_service_scope is None:
        raise ValueError("必须提供 search_service 或 search_service_scope。")
    if search_service is not None and search_service_scope is not None:
        raise ValueError("search_service 与 search_service_scope 只能二选一。")
    if search_service_scope is None:
        assert search_service is not None
        search_service_scope = lambda: nullcontext(search_service)

    app = FastAPI(title="agent-context-platform")

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response("invalid_request", "请求参数格式错误。", exc.errors())

    @app.post("/search-code")
    def search_code(request: SearchRequest) -> dict[str, list[dict[str, Any]]]:
        with search_service_scope() as scoped_search_service:
            return _search_endpoint(
                api_name="search-code",
                asset_type=AssetType.CODE,
                request=request,
                search_service=scoped_search_service,
            )

    @app.post("/search-db-schema")
    def search_db_schema(request: SearchRequest) -> dict[str, list[dict[str, Any]]]:
        with search_service_scope() as scoped_search_service:
            return _search_endpoint(
                api_name="search-db-schema",
                asset_type=AssetType.DB_SCHEMA,
                request=request,
                search_service=scoped_search_service,
            )

    @app.post("/search-doc")
    def search_doc(request: SearchRequest) -> dict[str, list[dict[str, Any]]]:
        with search_service_scope() as scoped_search_service:
            return _search_endpoint(
                api_name="search-doc",
                asset_type=AssetType.DOC,
                request=request,
                search_service=scoped_search_service,
            )

    @app.post("/build-task-context")
    def build_task_context(request: BuildTaskContextRequest) -> dict[str, Any]:
        started = time.perf_counter()
        request_id = request.request_id or str(uuid4())
        try:
            # API 层只负责请求/错误/日志包装，实际上下文聚合交给 TaskContextBuilder。
            with search_service_scope() as scoped_search_service:
                context = TaskContextBuilder(scoped_search_service).build(
                    task=request.task,
                    limits=request.limits,
                    constraints=request.constraints,
                )
        except (EmbeddingProviderError, EmbeddingDimensionError) as exc:
            logger.exception(
                "request_id=%s api=build-task-context error_code=embedding_unavailable",
                request_id,
            )
            return _error_response("embedding_unavailable", str(exc))
        except ValueError as exc:
            return _error_response("invalid_request", str(exc))
        except SQLAlchemyError as exc:
            logger.exception(
                "request_id=%s api=build-task-context error_code=storage_unavailable",
                request_id,
            )
            return _error_response("storage_unavailable", str(exc))

        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "request_id=%s api=build-task-context result_count=%s elapsed_ms=%s",
            request_id,
            len(context.citations),
            elapsed_ms,
        )
        return context.model_dump(mode="json")

    return app


def _search_endpoint(
    *,
    api_name: str,
    asset_type: AssetType,
    request: SearchRequest,
    search_service: HybridSearchService,
) -> dict[str, list[dict[str, Any]]] | JSONResponse:
    started = time.perf_counter()
    request_id = request.request_id or str(uuid4())
    try:
        # 三个 search endpoint 共用同一条路径，只通过 asset_type 区分代码、表结构和文档。
        results = search_service.search(
            HybridSearchQuery(
                query=request.query,
                asset_type=asset_type,
                limit=request.limit,
                filters=request.filters.model_dump(exclude_none=True),
                query_embedding=request.query_embedding,
            )
        )
    except (EmbeddingProviderError, EmbeddingDimensionError) as exc:
        logger.exception(
            "request_id=%s api=%s error_code=embedding_unavailable",
            request_id,
            api_name,
        )
        return _error_response("embedding_unavailable", str(exc))
    except ValueError as exc:
        return _error_response("invalid_request", str(exc))
    except SQLAlchemyError as exc:
        logger.exception(
            "request_id=%s api=%s error_code=storage_unavailable",
            request_id,
            api_name,
        )
        return _error_response("storage_unavailable", str(exc))

    _log_search(
        api_name=api_name,
        request_id=request_id,
        result_count=len(results),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return {"results": _dump_results(results)}


def _log_search(
    *, api_name: str, request_id: str, result_count: int, elapsed_ms: float
) -> None:
    logger.info(
        "request_id=%s api=%s result_count=%s elapsed_ms=%s",
        request_id,
        api_name,
        result_count,
        elapsed_ms,
    )


def _dump_results(results: list[SearchResult]) -> list[dict[str, Any]]:
    return [result.model_dump(mode="json") for result in results]


def _error_response(
    code: str, message: str, details: Any | None = None
) -> JSONResponse:
    # MCP 客户端会保留 error.code/message，因此这里保持稳定的错误 envelope。
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=400, content=body)
