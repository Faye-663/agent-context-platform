from __future__ import annotations

from typing import Any

from agent_context_platform.context_composer import ContextComposer, ContextGroups
from agent_context_platform.models import AssetType, SearchResult, TaskContext
from agent_context_platform.retrieval import HybridSearchQuery, HybridSearchService
from agent_context_platform.retrieval_trace import RetrievalTrace


class TaskContextBuilder:
    def __init__(
        self,
        search_service: HybridSearchService,
        composer: ContextComposer | None = None,
    ):
        self.search_service = search_service
        self.composer = composer or ContextComposer()
        self.last_traces: dict[str, RetrievalTrace | None] = {}
        self.last_version_mismatches: dict[str, bool] = {}

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
        if constraints.get("expected_commit_sha"):
            repo_filter["expected_commit_sha"] = constraints["expected_commit_sha"]

        # 代码、DB、文档分开搜，避免一种资产的高分结果挤掉其他必要上下文。
        related_code = self._search(
            "related_code",
            HybridSearchQuery(
                query=task,
                asset_type=AssetType.CODE,
                limit=limits.get("code", 8),
                filters={**repo_filter, **code_filters},
            )
        )
        related_db_schema = self._search(
            "related_db_schema",
            HybridSearchQuery(
                query=task,
                asset_type=AssetType.DB_SCHEMA,
                limit=limits.get("db_schema", 5),
                filters=repo_filter,
            )
        )
        related_docs = self._search(
            "related_docs",
            HybridSearchQuery(
                query=task,
                asset_type=AssetType.DOC,
                limit=limits.get("docs", 5),
                filters=repo_filter,
            )
        )
        similar_implementations = self._search(
            "similar_implementations",
            HybridSearchQuery(
                query=task,
                asset_type=AssetType.CODE,
                limit=limits.get("similar_implementations", 5),
                filters={**repo_filter, **code_filters, "symbol_type": ["method", "class"]},
            )
        )

        return self.composer.compose(
            query=task,
            groups=ContextGroups(
                related_code=related_code,
                related_db_schema=related_db_schema,
                related_docs=related_docs,
                similar_implementations=similar_implementations,
            ),
            token_budget=_optional_positive_int(constraints.get("token_budget")),
            version_mismatch=any(self.last_version_mismatches.values()),
        )

    def _search(
        self, group_name: str, search_query: HybridSearchQuery
    ) -> list[SearchResult]:
        """保留每个上下文分组的 trace，供 API debug response 无损展示。"""
        results = self.search_service.search(search_query)
        self.last_traces[group_name] = self.search_service.last_trace
        self.last_version_mismatches[group_name] = self.search_service.last_version_mismatch
        return results


def _optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("constraints.token_budget must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError("constraints.token_budget must be a positive integer")
    return parsed
