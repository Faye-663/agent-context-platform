from __future__ import annotations

from typing import Any

from agent_context_platform.models import AssetType, SearchResult, SourceCitation, TaskContext
from agent_context_platform.retrieval import HybridSearchQuery, HybridSearchService


class TaskContextBuilder:
    def __init__(self, search_service: HybridSearchService):
        self.search_service = search_service

    def build(
        self,
        *,
        task: str,
        limits: dict[str, int] | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> TaskContext:
        # Context Builder 是面向 Agent 的聚合层：同一个 task 会分别检索代码、表结构、文档和相似实现。
        limits = limits or {}
        constraints = constraints or {}

        code_filters: dict[str, Any] = {}
        if constraints.get("language"):
            code_filters["language"] = constraints["language"]
        repo_filter: dict[str, Any] = {}
        if constraints.get("repo"):
            repo_filter["repo"] = constraints["repo"]

        # 代码、DB、文档分开搜，避免一种资产的高分结果挤掉其他必要上下文。
        related_code = self.search_service.search(
            HybridSearchQuery(
                query=task,
                asset_type=AssetType.CODE,
                limit=limits.get("code", 8),
                filters={**repo_filter, **code_filters},
            )
        )
        related_db_schema = self.search_service.search(
            HybridSearchQuery(
                query=task,
                asset_type=AssetType.DB_SCHEMA,
                limit=limits.get("db_schema", 5),
                filters=repo_filter,
            )
        )
        related_docs = self.search_service.search(
            HybridSearchQuery(
                query=task,
                asset_type=AssetType.DOC,
                limit=limits.get("docs", 5),
                filters=repo_filter,
            )
        )
        similar_implementations = self.search_service.search(
            HybridSearchQuery(
                query=task,
                asset_type=AssetType.CODE,
                limit=limits.get("similar_implementations", 5),
                filters={**repo_filter, **code_filters, "symbol_type": ["method", "class"]},
            )
        )

        missing_context = _missing_context(related_code, related_db_schema, related_docs)
        # 缺失上下文不是异常：返回给调用方，让 Agent 知道哪些部分需要人工补充或扩大检索。
        risks = [
            f"未召回到 {asset_type} 上下文，需要人工确认。"
            for asset_type in missing_context
        ]
        return TaskContext(
            query=task,
            related_code=related_code,
            related_db_schema=related_db_schema,
            related_docs=related_docs,
            similar_implementations=similar_implementations,
            missing_context=missing_context,
            risks=risks,
            citations=_unique_citations(
                related_code
                + related_db_schema
                + related_docs
                + similar_implementations
            ),
        )


def _missing_context(
    related_code: list[SearchResult],
    related_db_schema: list[SearchResult],
    related_docs: list[SearchResult],
) -> list[str]:
    missing: list[str] = []
    if not related_code:
        missing.append("code")
    if not related_db_schema:
        missing.append("db_schema")
    if not related_docs:
        missing.append("doc")
    return missing


def _unique_citations(results: list[SearchResult]) -> list[SourceCitation]:
    # TaskContext 顶层 citations 去重，便于 Agent 快速展示所有可追溯来源。
    seen: set[str] = set()
    citations: list[SourceCitation] = []
    for result in results:
        key = result.source.model_dump_json()
        if key in seen:
            continue
        seen.add(key)
        citations.append(result.source)
    return citations
