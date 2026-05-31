from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from agent_context_platform.embeddings import (
    EmbeddingDimensionError,
    EmbeddingProvider,
)
from agent_context_platform.models import AssetType, SearchResult
from agent_context_platform.storage import IndexedItemRepository


@dataclass(frozen=True)
class HybridSearchQuery:
    """一次混合检索请求。

    例子：
    HybridSearchQuery(
        query="payment message build",
        asset_type=AssetType.CODE,
        filters={"language": "java", "symbol_type": ["method"]},
    )
    """

    # query 是用户或 Agent 的自然语言检索词。
    query: str
    # asset_type 限定检索资产类型，避免代码、表结构和文档互相挤占结果。
    asset_type: AssetType
    # limit 是最终返回条数；内部候选也用它控制召回上限。
    limit: int = 10
    # filters 承载结构化条件，例如 language、path_prefix、symbol_type、table。
    filters: dict[str, Any] = field(default_factory=dict)
    # query_embedding 可由调用方传入；不传时会尝试用 embedding_provider 生成。
    query_embedding: list[float] | None = None


class HybridSearchService:
    def __init__(
        self,
        repository: IndexedItemRepository,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        self.repository = repository
        self.embedding_provider = embedding_provider

    def search(self, search_query: HybridSearchQuery) -> list[SearchResult]:
        # search 是 RAG 检索编排层：它不解析文件、不直接写库，只合并 keyword 与 vector 候选。
        query = search_query.query.strip()
        if not query:
            raise ValueError("query must not be empty")

        filters = dict(search_query.filters or {})
        symbol_types = _as_string_list(filters.get("symbol_type"))
        query_embedding = search_query.query_embedding
        embedding_identity = None
        if self.embedding_provider is not None:
            # 有 provider 时必须绑定 provider/model/dimension，避免拿不同模型的向量互相比。
            embedding_identity = self.embedding_provider.identity
            if query_embedding is None:
                query_embedding = _embed_query_text(self.embedding_provider, query)
            elif len(query_embedding) != embedding_identity.dimension:
                raise EmbeddingDimensionError(
                    "query embedding dimension mismatch for "
                    f"{embedding_identity.provider}/{embedding_identity.model}: "
                    f"expected {embedding_identity.dimension}, got {len(query_embedding)}"
                )

        tokens = _query_tokens(query)
        candidate_limit = max(1, search_query.limit)
        candidate_vectors: dict[str, float] = {}
        candidates: dict[str, Any] = {}
        if query_embedding is not None and embedding_identity is not None:
            # PostgreSQL 路径由 repository 下推给 pgvector；SQLite 测试路径保留轻量替代实现。
            for item, vector_score in self.repository.search_by_vector(
                asset_type=search_query.asset_type,
                path_prefix=filters.get("path_prefix"),
                language=filters.get("language"),
                symbol_types=symbol_types,
                table=filters.get("table"),
                query_embedding=query_embedding,
                embedding_identity=embedding_identity,
                limit=candidate_limit,
            ):
                candidates[item.id] = item
                candidate_vectors[item.id] = vector_score
        elif query_embedding is not None:
            # 兼容手动传 query_embedding 但没有 provider 的测试场景；生产路径应优先带 identity。
            for item, embedding in self.repository.list_with_embeddings(
                asset_type=search_query.asset_type,
                path_prefix=filters.get("path_prefix"),
                language=filters.get("language"),
                symbol_types=symbol_types,
                table=filters.get("table"),
                embedding_identity=embedding_identity,
            ):
                candidates[item.id] = item
                candidate_vectors[item.id] = _vector_score(query_embedding, embedding)

        # keyword 召回始终执行，用来补足“向量相似但关键词不明显”或“尚未生成 embedding”的资产。
        for item in self.repository.list_keyword_candidates(
            asset_type=search_query.asset_type,
            path_prefix=filters.get("path_prefix"),
            language=filters.get("language"),
            symbol_types=symbol_types,
            table=filters.get("table"),
            keywords=sorted(tokens),
            limit=candidate_limit,
        ):
            candidates.setdefault(item.id, item)

        results: list[SearchResult] = []
        for item in candidates.values():
            keyword_score, matched_tokens = _keyword_score(item, tokens)
            vector_score = candidate_vectors.get(item.id, 0.0)
            # 当前权重偏向 keyword，便于早期工程检索保持可解释；后续评测可再调整。
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


def _embed_query_text(provider: EmbeddingProvider, query: str) -> list[float]:
    embed_query = getattr(provider, "embed_query", None)
    if callable(embed_query):
        return list(embed_query(query))
    return provider.embed_texts([query])[0]


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
    # keyword 分数只看 IndexedItem 的可解释字段，不把 source 行号等定位信息当作相关性信号。
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
