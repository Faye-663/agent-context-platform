from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from agent_context_platform.models import AssetType, SearchResult
from agent_context_platform.storage import IndexedItemRepository


@dataclass(frozen=True)
class HybridSearchQuery:
    query: str
    asset_type: AssetType
    limit: int = 10
    filters: dict[str, Any] = field(default_factory=dict)
    query_embedding: list[float] | None = None


class HybridSearchService:
    def __init__(self, repository: IndexedItemRepository):
        self.repository = repository

    def search(self, search_query: HybridSearchQuery) -> list[SearchResult]:
        query = search_query.query.strip()
        if not query:
            raise ValueError("query must not be empty")

        filters = dict(search_query.filters or {})
        symbol_types = _as_string_list(filters.get("symbol_type"))
        candidates = self.repository.list_with_embeddings(
            asset_type=search_query.asset_type,
            path_prefix=filters.get("path_prefix"),
            language=filters.get("language"),
            symbol_types=symbol_types,
            table=filters.get("table"),
        )

        tokens = _query_tokens(query)
        results: list[SearchResult] = []
        for item, embedding in candidates:
            keyword_score, matched_tokens = _keyword_score(item, tokens)
            vector_score = _vector_score(search_query.query_embedding, embedding)
            score = round(keyword_score * 0.7 + vector_score * 0.3, 6)
            if score <= 0:
                continue

            score_parts = {
                "keyword": round(keyword_score, 6),
                "vector": round(vector_score, 6),
            }
            results.append(
                SearchResult(
                    item=item,
                    score=score,
                    score_parts=score_parts,
                    match_reason=_match_reason(matched_tokens, vector_score),
                    source=item.source,
                )
            )

        return sorted(results, key=lambda result: (-result.score, result.item.id))[
            : search_query.limit
        ]


def _as_string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _query_tokens(text: str) -> set[str]:
    normalized = text.lower()
    tokens = {token for token in re.findall(r"[a-z0-9_]+", normalized) if len(token) > 1}
    # 中文任务描述通常没有空格，补充 bigram 可以支持“支付报文”这类短语命中。
    for segment in re.findall(r"[\u4e00-\u9fff]+", normalized):
        tokens.update(segment[index : index + 2] for index in range(len(segment) - 1))
    return tokens


def _keyword_score(item: Any, tokens: set[str]) -> tuple[float, list[str]]:
    if not tokens:
        return 0.0, []
    haystack = " ".join(
        [
            item.title,
            item.content,
            item.summary,
            " ".join(str(value) for value in item.metadata.values()),
        ]
    ).lower()
    matched = sorted(token for token in tokens if token in haystack)
    return len(matched) / len(tokens), matched


def _vector_score(
    query_embedding: list[float] | None, item_embedding: list[float] | None
) -> float:
    if not query_embedding or not item_embedding:
        return 0.0
    if len(query_embedding) != len(item_embedding):
        return 0.0

    dot = sum(left * right for left, right in zip(query_embedding, item_embedding))
    query_norm = math.sqrt(sum(value * value for value in query_embedding))
    item_norm = math.sqrt(sum(value * value for value in item_embedding))
    if query_norm == 0 or item_norm == 0:
        return 0.0
    return max(0.0, dot / (query_norm * item_norm))


def _match_reason(matched_tokens: list[str], vector_score: float) -> str:
    parts: list[str] = []
    if matched_tokens:
        parts.append(f"keyword hit: {', '.join(matched_tokens[:5])}")
    if vector_score > 0:
        parts.append("vector similarity hit")
    return "; ".join(parts) if parts else "no match"
