from __future__ import annotations

from dataclasses import dataclass

from agent_context_platform.models import ContextRisk, SearchResult, SourceCitation, TaskContext


@dataclass(frozen=True)
class ContextGroups:
    related_code: list[SearchResult]
    related_db_schema: list[SearchResult]
    related_docs: list[SearchResult]
    similar_implementations: list[SearchResult]


class ContextComposer:
    def compose(
        self,
        *,
        query: str,
        groups: ContextGroups,
        token_budget: int | None = None,
        version_mismatch: bool = False,
    ) -> TaskContext:
        related_code = list(groups.related_code)
        related_db_schema = list(groups.related_db_schema)
        related_docs = list(groups.related_docs)
        similar_implementations = list(groups.similar_implementations)

        related_code, related_db_schema, similar_implementations, related_docs = _classify_and_dedupe(
            related_code, related_db_schema, similar_implementations, related_docs
        )

        if token_budget is not None:
            related_code, related_db_schema, related_docs, similar_implementations = (
                _apply_token_budget(
                    token_budget,
                    related_code,
                    related_db_schema,
                    related_docs,
                    similar_implementations,
                )
            )

        missing_context = _missing_context(related_code, related_db_schema, related_docs)
        risks = _risks(
            related_code=related_code,
            related_db_schema=related_db_schema,
            related_docs=related_docs,
            missing_context=missing_context,
            version_mismatch=version_mismatch,
        )
        citations = _unique_citations(
            related_code + related_db_schema + related_docs + similar_implementations
        )
        return TaskContext(
            query=query,
            result_status="ok" if citations else "empty",
            related_code=related_code,
            related_db_schema=related_db_schema,
            related_docs=related_docs,
            similar_implementations=similar_implementations,
            missing_context=missing_context,
            risks=risks,
            citations=citations,
        )


def _apply_token_budget(
    token_budget: int,
    related_code: list[SearchResult],
    related_db_schema: list[SearchResult],
    related_docs: list[SearchResult],
    similar_implementations: list[SearchResult],
) -> tuple[
    list[SearchResult],
    list[SearchResult],
    list[SearchResult],
    list[SearchResult],
]:
    if token_budget <= 0:
        return [], [], [], []

    remaining = token_budget
    kept_groups: list[list[SearchResult]] = []
    any_kept = False
    for group in [related_code, related_db_schema, related_docs, similar_implementations]:
        kept: list[SearchResult] = []
        for result in group:
            cost = _estimate_result_tokens(result)
            if cost > remaining and kept:
                continue
            if cost > remaining and not any_kept:
                kept.append(result)
                any_kept = True
                remaining = 0
                break
            if cost <= remaining:
                kept.append(result)
                any_kept = True
                remaining -= cost
        kept_groups.append(kept)
    return kept_groups[0], kept_groups[1], kept_groups[2], kept_groups[3]


def _classify_and_dedupe(
    related_code: list[SearchResult],
    related_db_schema: list[SearchResult],
    similar_implementations: list[SearchResult],
    related_docs: list[SearchResult],
) -> tuple[list[SearchResult], list[SearchResult], list[SearchResult], list[SearchResult]]:
    seen: set[str] = set()

    def keep(results: list[SearchResult], role: str) -> list[SearchResult]:
        kept: list[SearchResult] = []
        for result in results:
            key = result.source.model_dump_json()
            if key in seen:
                continue
            seen.add(key)
            kept.append(result.model_copy(update={"evidence_role": role}))
        return kept

    return (
        keep(related_code, "primary"),
        keep(related_db_schema, "primary"),
        keep(similar_implementations, "related"),
        keep(related_docs, "background"),
    )


def _estimate_result_tokens(result: SearchResult) -> int:
    text = " ".join(
        [
            result.item.title,
            result.item.summary,
            result.item.content,
            result.match_reason,
        ]
    )
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, ascii_chars // 4 + non_ascii_chars // 2)


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


def _risks(
    *,
    related_code: list[SearchResult],
    related_db_schema: list[SearchResult],
    related_docs: list[SearchResult],
    missing_context: list[str],
    version_mismatch: bool,
) -> list[ContextRisk]:
    risks = [
        ContextRisk(
            code="MISSING_CONTEXT",
            message=f"未召回到 {asset_type} 上下文，需要人工确认。",
        )
        for asset_type in missing_context
    ]
    all_results = related_code + related_db_schema + related_docs
    if all_results and max(result.score for result in all_results) < 0.01:
        risks.append(ContextRisk(code="LOW_CONFIDENCE", message="召回结果整体置信度较低，建议扩大检索或补充关键词。"))
    if _has_missing_provenance(all_results):
        risks.append(ContextRisk(code="INCOMPLETE_PROVENANCE", message="部分上下文缺少 file_hash 或 indexed_at，无法完整判断索引新鲜度。"))
    if version_mismatch:
        risks.append(ContextRisk(code="STALE_INDEX", message="存在不匹配指定 commit 的候选，已严格排除。"))
    return risks


def _has_missing_provenance(results: list[SearchResult]) -> bool:
    for result in results:
        source = result.source
        if source.source_type.value in {"code", "doc"}:
            if not source.file_hash or source.indexed_at is None:
                return True
    return False


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
