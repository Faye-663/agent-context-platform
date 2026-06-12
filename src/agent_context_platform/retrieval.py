from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_context_platform.aliases import AliasExpansion, DomainVocabulary
from agent_context_platform.embeddings import (
    EmbeddingDimensionError,
    EmbeddingProvider,
)
from agent_context_platform.lexical import LexicalScore, score_documents, tokenize_query
from agent_context_platform.models import AssetType, IndexedItem, SearchResult, SymbolCatalogEntry
from agent_context_platform.retrieval_trace import RecallHit, RetrievalTrace, reciprocal_rank_fusion
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
    # filters 承载结构化条件，例如 repo、language、path_prefix、symbol_type、table。
    filters: dict[str, Any] = field(default_factory=dict)
    # query_embedding 可由调用方传入；不传时会尝试用 embedding_provider 生成。
    query_embedding: list[float] | None = None


class HybridSearchService:
    def __init__(
        self,
        repository: IndexedItemRepository,
        embedding_provider: EmbeddingProvider | None = None,
        domain_vocabulary: DomainVocabulary | None = None,
        *,
        rrf_k: int = 60,
    ):
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.domain_vocabulary = domain_vocabulary or DomainVocabulary.empty()
        self.rrf_k = rrf_k
        self.last_trace: RetrievalTrace | None = None

    def search(self, search_query: HybridSearchQuery) -> list[SearchResult]:
        # search 是 RAG 检索编排层：它不解析文件、不直接写库，只合并多路召回候选。
        query = search_query.query.strip()
        if not query:
            raise ValueError("query must not be empty")

        filters = dict(search_query.filters or {})
        repo = filters.get("repo")
        symbol_types = _as_string_list(filters.get("symbol_type"))
        alias_expansions = self.domain_vocabulary.expand_query(query)
        expanded_query = _expanded_query_text(query, alias_expansions)
        token_set = tokenize_query(
            expanded_query,
            domain_terms=self.domain_vocabulary.terms,
        )
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

        candidate_limit = max(search_query.limit * 3, 20)
        recall_hits: list[RecallHit] = []
        recall_hits.extend(
            self._lexical_recall(
                asset_type=search_query.asset_type,
                repo=repo,
                path_prefix=filters.get("path_prefix"),
                language=filters.get("language"),
                symbol_types=symbol_types,
                table=filters.get("table"),
                query_tokens=token_set.tokens,
                limit=candidate_limit,
            )
        )
        if query_embedding is not None and embedding_identity is not None:
            # PostgreSQL 路径由 repository 下推给 pgvector；SQLite 测试路径保留轻量替代实现。
            recall_hits.extend(
                _ranked_hits(
                    "vector",
                    [
                        (item, vector_score, "vector similarity hit")
                        for item, vector_score in self.repository.search_by_vector(
                            repo=repo,
                            asset_type=search_query.asset_type,
                            path_prefix=filters.get("path_prefix"),
                            language=filters.get("language"),
                            symbol_types=symbol_types,
                            table=filters.get("table"),
                            query_embedding=query_embedding,
                            embedding_identity=embedding_identity,
                            limit=candidate_limit,
                        )
                    ],
                )
            )
        elif query_embedding is not None:
            # 兼容手动传 query_embedding 但没有 provider 的测试场景；生产路径应优先带 identity。
            recall_hits.extend(
                _ranked_hits(
                    "vector",
                    [
                        (
                            item,
                            _vector_score(query_embedding, embedding),
                            "vector similarity hit",
                        )
                        for item, embedding in self.repository.list_with_embeddings(
                            repo=repo,
                            asset_type=search_query.asset_type,
                            path_prefix=filters.get("path_prefix"),
                            language=filters.get("language"),
                            symbol_types=symbol_types,
                            table=filters.get("table"),
                            embedding_identity=embedding_identity,
                        )
                    ],
                )
            )

        recall_hits.extend(
            self._symbol_recall(
                asset_type=search_query.asset_type,
                repo=repo,
                path_prefix=filters.get("path_prefix"),
                language=filters.get("language"),
                symbol_types=symbol_types,
                query_terms=token_set.symbol_terms + token_set.tokens,
                limit=candidate_limit,
            )
        )

        fused_candidates = reciprocal_rank_fusion(
            recall_hits,
            final_limit=search_query.limit,
            rrf_k=self.rrf_k,
        )
        self.last_trace = RetrievalTrace(
            query=query,
            query_tokens=token_set.tokens,
            alias_expansions=tuple(_alias_labels(alias_expansions)),
            hits=tuple(recall_hits),
            fused=tuple(fused_candidates),
        )

        results: list[SearchResult] = []
        for candidate in fused_candidates:
            score_parts = _score_parts(candidate.channel_scores, candidate.score)
            results.append(
                SearchResult(
                    item=candidate.item,
                    score=candidate.score,
                    score_parts=score_parts,
                    match_reason=_match_reason(candidate.reasons),
                    source=candidate.item.source,
                )
            )
        return results

    def _lexical_recall(
        self,
        *,
        asset_type: AssetType,
        repo: str | None,
        path_prefix: str | None,
        language: str | None,
        symbol_types: list[str] | None,
        table: str | None,
        query_tokens: tuple[str, ...],
        limit: int,
    ) -> list[RecallHit]:
        if not query_tokens:
            return []
        candidates = self.repository.list_keyword_candidates(
            repo=repo,
            asset_type=asset_type,
            path_prefix=path_prefix,
            language=language,
            symbol_types=symbol_types,
            table=table,
            keywords=sorted(query_tokens),
            limit=limit,
        )
        scores = score_documents(
            query_tokens,
            candidates,
            domain_terms=self.domain_vocabulary.terms,
        )
        ranked: list[tuple[IndexedItem, LexicalScore, str]] = []
        for item in candidates:
            lexical_score = scores.get((item.source.repo, item.id))
            if lexical_score is None:
                continue
            reason = (
                "keyword/lexical hit: "
                + ", ".join(lexical_score.matched_tokens[:5])
                + " fields="
                + ",".join(lexical_score.matched_fields[:5])
            )
            ranked.append((item, lexical_score, reason))
        ranked.sort(key=lambda row: (-row[1].score, row[0].source.repo or "", row[0].id))
        return [
            RecallHit(
                channel="lexical",
                item=item,
                rank=index,
                raw_score=score.score,
                reason=reason,
            )
            for index, (item, score, reason) in enumerate(ranked, start=1)
        ]

    def _symbol_recall(
        self,
        *,
        asset_type: AssetType,
        repo: str | None,
        path_prefix: str | None,
        language: str | None,
        symbol_types: list[str] | None,
        query_terms: tuple[str, ...],
        limit: int,
    ) -> list[RecallHit]:
        if not repo or asset_type not in {AssetType.CODE, AssetType.DB_SCHEMA}:
            return []
        kinds = _symbol_kinds(asset_type, symbol_types)
        symbols = self.repository.list_symbols(
            repo=repo,
            path_prefix=path_prefix,
            language=language,
            kinds=kinds,
        )
        scored_symbols = _score_symbols(symbols, query_terms)
        hits: list[tuple[IndexedItem, float, str]] = []
        seen: set[tuple[str | None, str]] = set()
        for symbol, symbol_score, reason in scored_symbols:
            if symbol.source_item_id is None:
                continue
            item = self.repository.get(symbol.source_item_id, repo=symbol.repo)
            if item is None or item.asset_type is not asset_type:
                continue
            key = (item.source.repo, item.id)
            if key in seen:
                continue
            seen.add(key)
            hits.append((item, symbol_score, reason))
            if len(hits) >= limit:
                break
        return _ranked_hits("symbol", hits)


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


def _vector_score(
    query_embedding: list[float] | None, item_embedding: list[float] | None
) -> float:
    if not query_embedding or not item_embedding:
        return 0.0
    if len(query_embedding) != len(item_embedding):
        return 0.0

    import math

    dot = sum(left * right for left, right in zip(query_embedding, item_embedding))
    query_norm = math.sqrt(sum(value * value for value in query_embedding))
    item_norm = math.sqrt(sum(value * value for value in item_embedding))
    if query_norm == 0 or item_norm == 0:
        return 0.0
    return max(0.0, dot / (query_norm * item_norm))


def _expanded_query_text(query: str, alias_expansions: list[AliasExpansion]) -> str:
    values = [query]
    for expansion in alias_expansions:
        values.append(expansion.term)
        values.extend(expansion.expands_to)
    return " ".join(values)


def _alias_labels(alias_expansions: list[AliasExpansion]) -> list[str]:
    return [
        f"{expansion.term} -> {', '.join(expansion.expands_to)}"
        for expansion in alias_expansions
    ]


def _ranked_hits(
    channel: str,
    hits: list[tuple[IndexedItem, float, str]],
) -> list[RecallHit]:
    ranked = [
        (item, score, reason)
        for item, score, reason in hits
        if score > 0
    ]
    ranked.sort(key=lambda row: (-row[1], row[0].source.repo or "", row[0].id))
    return [
        RecallHit(
            channel=channel,
            item=item,
            rank=index,
            raw_score=round(score, 6),
            reason=reason,
        )
        for index, (item, score, reason) in enumerate(ranked, start=1)
    ]


def _symbol_kinds(asset_type: AssetType, symbol_types: list[str] | None) -> list[str]:
    if symbol_types:
        return list(symbol_types)
    if asset_type is AssetType.CODE:
        return [
            "annotation_type",
            "class",
            "constructor",
            "enum",
            "field",
            "interface",
            "method",
            "record",
        ]
    if asset_type is AssetType.DB_SCHEMA:
        return ["table", "column"]
    return []


def _score_symbols(
    symbols: list[SymbolCatalogEntry],
    query_terms: tuple[str, ...],
) -> list[tuple[SymbolCatalogEntry, float, str]]:
    normalized_terms = sorted({term for term in query_terms if len(term) > 1}, key=len, reverse=True)
    scored: list[tuple[SymbolCatalogEntry, float, str]] = []
    for symbol in symbols:
        symbol_values = [
            symbol.name,
            symbol.qualified_name,
            symbol.symbol_id,
        ]
        lowered_values = [value.lower() for value in symbol_values]
        best_score = 0.0
        best_reason = ""
        for term in normalized_terms:
            lowered_term = term.lower()
            if lowered_term in lowered_values:
                best_score = 1.0
                best_reason = f"symbol exact hit: {term}"
                break
            if any(value.startswith(lowered_term) for value in lowered_values):
                if best_score < 0.85:
                    best_score = 0.85
                    best_reason = f"symbol prefix hit: {term}"
            elif any(lowered_term in value for value in lowered_values):
                if best_score < 0.65:
                    best_score = 0.65
                    best_reason = f"symbol fuzzy hit: {term}"
        if best_score > 0:
            scored.append((symbol, best_score, best_reason))
    scored.sort(key=lambda row: (-row[1], row[0].qualified_name, row[0].symbol_id))
    return scored


def _score_parts(channel_scores: dict[str, float], rrf_score: float) -> dict[str, float]:
    lexical_score = round(channel_scores.get("lexical", 0.0), 6)
    parts = {
        "keyword": lexical_score,
        "lexical": lexical_score,
        "vector": round(channel_scores.get("vector", 0.0), 6),
        "symbol": round(channel_scores.get("symbol", 0.0), 6),
        "rrf": round(rrf_score, 6),
    }
    return parts


def _match_reason(reasons: tuple[str, ...]) -> str:
    return "; ".join(reasons[:4]) if reasons else "no match"
