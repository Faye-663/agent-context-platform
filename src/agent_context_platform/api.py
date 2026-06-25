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
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from agent_context_platform.context_builder import TaskContextBuilder
from agent_context_platform.embeddings import (
    EmbeddingDimensionError,
    EmbeddingProviderError,
)
from agent_context_platform.models import AssetType, SearchResult
from agent_context_platform.retrieval import HybridSearchQuery, HybridSearchService
from agent_context_platform.retrieval_trace import RetrievalTrace


logger = logging.getLogger(__name__)
SearchServiceScope = Callable[[], AbstractContextManager[HybridSearchService]]


class DebugOptions(BaseModel):
    """调试参数分组。不传时使用默认行为。"""

    model_config = ConfigDict(extra="forbid")

    # query_embedding 用于绕过 provider 直接传查询向量，常见于测试或上游已生成向量的场景。
    query_embedding: list[float] | None = None
    # include_trace 为 True 时在 response 中返回检索 trace（调试用途，结构可能随版本变化）。
    include_trace: bool = False


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
    # repo 限定 GitLab code repo identity，例如 "gitlab.example.com/group/project"。
    repo: str | None = None


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
    # debug_options 调试参数分组，包含 query_embedding 和 include_trace。
    debug_options: DebugOptions | None = None
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
    # debug_options 调试参数分组，包含 query_embedding 和 include_trace。
    debug_options: DebugOptions | None = None
    # request_id 用于日志追踪；不传时 API 会自动生成。
    request_id: str | None = None


def create_app(
    search_service: HybridSearchService | None = None,
    *,
    search_service_scope: SearchServiceScope | None = None,
    default_repo: str | None = None,
    require_repo_filter: bool = False,
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
    def search_code(request: SearchRequest) -> dict[str, Any]:
        with search_service_scope() as scoped_search_service:
            return _search_endpoint(
                api_name="search-code",
                asset_type=AssetType.CODE,
                request=request,
                search_service=scoped_search_service,
                default_repo=default_repo,
                require_repo_filter=require_repo_filter,
            )

    @app.post("/search-db-schema")
    def search_db_schema(request: SearchRequest) -> dict[str, Any]:
        with search_service_scope() as scoped_search_service:
            return _search_endpoint(
                api_name="search-db-schema",
                asset_type=AssetType.DB_SCHEMA,
                request=request,
                search_service=scoped_search_service,
                default_repo=default_repo,
                require_repo_filter=require_repo_filter,
            )

    @app.post("/search-doc")
    def search_doc(request: SearchRequest) -> dict[str, Any]:
        with search_service_scope() as scoped_search_service:
            return _search_endpoint(
                api_name="search-doc",
                asset_type=AssetType.DOC,
                request=request,
                search_service=scoped_search_service,
                default_repo=default_repo,
                require_repo_filter=require_repo_filter,
            )

    @app.post("/build-task-context")
    def build_task_context(request: BuildTaskContextRequest) -> dict[str, Any]:
        started = time.perf_counter()
        request_id = request.request_id or str(uuid4())
        try:
            # API 层只负责请求/错误/日志包装，实际上下文聚合交给 TaskContextBuilder。
            with search_service_scope() as scoped_search_service:
                builder = TaskContextBuilder(scoped_search_service)
                context = builder.build(
                    task=request.task,
                    limits=request.limits,
                    constraints=_constraints_with_repo(
                        request.constraints,
                        default_repo=default_repo,
                        require_repo_filter=require_repo_filter,
                    ),
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
        response: dict[str, Any] = context.model_dump(mode="json")
        if _should_include_trace(request.debug_options):
            response["_trace"] = {
                "query": request.task,
                "queries": {
                    name: _serialize_retrieval_trace(trace)
                    for name, trace in builder.last_traces.items()
                },
            }
        return response

    return app


def _search_endpoint(
    *,
    api_name: str,
    asset_type: AssetType,
    request: SearchRequest,
    search_service: HybridSearchService,
    default_repo: str | None,
    require_repo_filter: bool,
) -> dict[str, Any] | JSONResponse:
    started = time.perf_counter()
    request_id = request.request_id or str(uuid4())
    try:
        filters = request.filters.model_dump(exclude_none=True)
        filters = _filters_with_repo(
            filters,
            default_repo=default_repo,
            require_repo_filter=require_repo_filter,
        )
        # 从 debug_options 中提取 query_embedding（如果有）
        query_embedding = (
            request.debug_options.query_embedding
            if request.debug_options
            else None
        )
        # 三个 search endpoint 共用同一条路径，只通过 asset_type 区分代码、表结构和文档。
        results = search_service.search(
            HybridSearchQuery(
                query=request.query,
                asset_type=asset_type,
                limit=request.limit,
                filters=filters,
                query_embedding=query_embedding,
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
    response: dict[str, Any] = {"results": _dump_results(results)}
    if _should_include_trace(request.debug_options):
        response["_trace"] = _serialize_retrieval_trace(search_service.last_trace)
    return response


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


def _filters_with_repo(
    filters: dict[str, Any],
    *,
    default_repo: str | None,
    require_repo_filter: bool,
) -> dict[str, Any]:
    resolved = dict(filters)
    if not resolved.get("repo") and default_repo:
        resolved["repo"] = default_repo
    if require_repo_filter and not resolved.get("repo"):
        raise ValueError("repo filter is required")
    return resolved


def _constraints_with_repo(
    constraints: dict[str, Any],
    *,
    default_repo: str | None,
    require_repo_filter: bool,
) -> dict[str, Any]:
    resolved = dict(constraints)
    if not resolved.get("repo") and default_repo:
        resolved["repo"] = default_repo
    if require_repo_filter and not resolved.get("repo"):
        raise ValueError("repo constraint is required")
    return resolved


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


def _should_include_trace(debug_options: DebugOptions | None) -> bool:
    return debug_options is not None and debug_options.include_trace


def _build_trace_from_results(
    results: list[SearchResult],
    query: str = "",
) -> dict[str, Any]:
    """从 SearchResult 列表中提取 trace 信息。

    当前从 score_parts 和各 channel 分数中汇总，提供各通道的候选数和
    最高分概览。详细 trace（tokenization、alias、per-item channel ranks）
    需要 retrieval.py 暴露内部 RetrievalTrace 后才能补充。
    """
    channel_info: dict[str, dict[str, Any]] = {}
    seen_keys: set[tuple[str | None, str]] = set()

    for result in results:
        key = (result.source.repo, result.item.id)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        score_parts = result.score_parts or {}
        for channel, score in score_parts.items():
            if channel not in channel_info:
                channel_info[channel] = {
                    "candidates": 0,
                    "top_score": 0.0,
                }
            channel_info[channel]["candidates"] += 1
            channel_info[channel]["top_score"] = max(
                channel_info[channel]["top_score"], score
            )

    fused = []
    for result in results:
        score_parts = result.score_parts or {}
        # channel_scores: 各通道对当前 item 的原始评分
        channel_scores = {
            ch: score for ch, score in score_parts.items() if score
        }
        # channel_ranks 需要 per-channel 完整排序，当前从 SearchResult
        # 无法获取；TODO: 等 retrieval.py 暴露 RetrievalTrace 后补充
        channel_ranks: dict[str, int] = {}
        fused.append({
            "item_id": result.item.id,
            "rrf_score": result.score,
            "channel_ranks": channel_ranks,
            "channel_scores": channel_scores,
        })

    return {
        "query": query,
        "query_tokens": [],
        "alias_expansions": [],
        "channels": channel_info,
        "fused": fused,
    }


def _serialize_retrieval_trace(trace: RetrievalTrace | None) -> dict[str, Any]:
    """将检索层 trace 原样转换为仅供 debug 使用的 JSON 结构。"""
    if trace is None:
        return {
            "query": "",
            "query_tokens": [],
            "alias_expansions": [],
            "channels": {},
            "fused": [],
        }

    channels: dict[str, list[dict[str, Any]]] = {}
    for hit in trace.hits:
        channels.setdefault(hit.channel, []).append(
            {
                "item_id": hit.item.id,
                "rank": hit.rank,
                "raw_score": hit.raw_score,
                "reason": hit.reason,
            }
        )

    return {
        "query": trace.query,
        "query_tokens": list(trace.query_tokens),
        "alias_expansions": list(trace.alias_expansions),
        "channels": {
            channel: {"candidate_count": len(hits), "hits": hits}
            for channel, hits in channels.items()
        },
        "fused": [
            {
                "item_id": candidate.item.id,
                "rrf_score": candidate.score,
                "channel_ranks": candidate.channel_ranks,
                "channel_scores": candidate.channel_scores,
                "reasons": list(candidate.reasons),
            }
            for candidate in trace.fused
        ],
    }
