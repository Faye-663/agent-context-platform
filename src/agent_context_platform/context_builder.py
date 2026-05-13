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
        limits = limits or {}
        constraints = constraints or {}

        code_filters: dict[str, Any] = {}
        if constraints.get("language"):
            code_filters["language"] = constraints["language"]

        related_code = self.search_service.search(
            HybridSearchQuery(
                query=task,
                asset_type=AssetType.CODE,
                limit=limits.get("code", 8),
                filters=code_filters,
            )
        )
        related_db_schema = self.search_service.search(
            HybridSearchQuery(
                query=task,
                asset_type=AssetType.DB_SCHEMA,
                limit=limits.get("db_schema", 5),
            )
        )
        related_docs = self.search_service.search(
            HybridSearchQuery(
                query=task,
                asset_type=AssetType.DOC,
                limit=limits.get("docs", 5),
            )
        )
        similar_implementations = self.search_service.search(
            HybridSearchQuery(
                query=task,
                asset_type=AssetType.CODE,
                limit=limits.get("similar_implementations", 5),
                filters={**code_filters, "symbol_type": ["method", "class"]},
            )
        )

        missing_context = _missing_context(related_code, related_db_schema, related_docs)
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
    seen: set[str] = set()
    citations: list[SourceCitation] = []
    for result in results:
        key = result.source.model_dump_json()
        if key in seen:
            continue
        seen.add(key)
        citations.append(result.source)
    return citations
