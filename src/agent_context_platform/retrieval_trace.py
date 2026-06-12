from __future__ import annotations

from dataclasses import dataclass, field

from agent_context_platform.models import IndexedItem


CandidateKey = tuple[str | None, str]


@dataclass(frozen=True)
class RecallHit:
    channel: str
    item: IndexedItem
    rank: int
    raw_score: float
    reason: str

    @property
    def key(self) -> CandidateKey:
        return (self.item.source.repo, self.item.id)


@dataclass(frozen=True)
class FusedCandidate:
    item: IndexedItem
    score: float
    channel_scores: dict[str, float]
    channel_ranks: dict[str, int]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalTrace:
    query: str
    query_tokens: tuple[str, ...]
    alias_expansions: tuple[str, ...]
    hits: tuple[RecallHit, ...]
    fused: tuple[FusedCandidate, ...]


@dataclass
class _FusionAccumulator:
    item: IndexedItem
    score: float = 0.0
    channel_scores: dict[str, float] = field(default_factory=dict)
    channel_ranks: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def reciprocal_rank_fusion(
    hits: list[RecallHit],
    *,
    final_limit: int,
    rrf_k: int = 60,
) -> list[FusedCandidate]:
    accumulators: dict[CandidateKey, _FusionAccumulator] = {}
    for hit in hits:
        accumulator = accumulators.setdefault(
            hit.key,
            _FusionAccumulator(item=hit.item),
        )
        accumulator.score += 1.0 / (rrf_k + hit.rank)
        accumulator.channel_scores[hit.channel] = max(
            hit.raw_score,
            accumulator.channel_scores.get(hit.channel, 0.0),
        )
        accumulator.channel_ranks[hit.channel] = min(
            hit.rank,
            accumulator.channel_ranks.get(hit.channel, hit.rank),
        )
        if hit.reason and hit.reason not in accumulator.reasons:
            accumulator.reasons.append(hit.reason)

    fused = [
        FusedCandidate(
            item=accumulator.item,
            score=round(accumulator.score, 6),
            channel_scores=dict(sorted(accumulator.channel_scores.items())),
            channel_ranks=dict(sorted(accumulator.channel_ranks.items())),
            reasons=tuple(accumulator.reasons),
        )
        for accumulator in accumulators.values()
    ]
    return sorted(
        fused,
        key=lambda candidate: (
            -candidate.score,
            candidate.item.source.repo or "",
            candidate.item.id,
        ),
    )[:final_limit]
