from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExpectedHit(BaseModel):
    source_type: str
    path: str | None = None
    symbol: str | None = None
    table: str | None = None
    column: str | None = None
    heading_path: str | None = None


class EvaluationSample(BaseModel):
    id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    expected_hits: list[ExpectedHit] = Field(min_length=1)
    irrelevant_result_ids: list[str] = Field(default_factory=list)
    irrelevant_rules: list[str] = Field(default_factory=list)
    notes: str | None = None


class EvaluationSampleResult(BaseModel):
    id: str
    task: str
    hit_expected_source: bool
    irrelevant_result_count: int
    missing_source_result_ids: list[str]
    top10_result_sources: list[dict[str, Any]]


class EvaluationReport(BaseModel):
    sample_count: int
    passed: bool
    top5_hit_rate: float
    top10_irrelevant_result_count: int
    source_citation_completeness: float
    failed_sample_ids: list[str]
    samples: list[EvaluationSampleResult]


def evaluate_context_payloads(
    samples: list[EvaluationSample],
    payloads_by_sample_id: dict[str, dict[str, Any]],
    *,
    min_top5_hit_rate: float = 0.7,
    max_top10_irrelevant_result_count: int = 3,
) -> EvaluationReport:
    sample_results: list[EvaluationSampleResult] = []
    hit_count = 0
    returned_result_count = 0
    sourced_result_count = 0
    total_irrelevant_count = 0

    for sample in samples:
        payload = payloads_by_sample_id.get(sample.id, {})
        results = _flatten_context_results(payload)
        top5 = results[:5]
        top10 = results[:10]
        hit_expected_source = any(
            _source_matches_expected(result.get("source"), expected)
            for result in top5
            for expected in sample.expected_hits
        )
        if hit_expected_source:
            hit_count += 1

        missing_source_result_ids = [
            _result_id(result) for result in results if not result.get("source")
        ]
        irrelevant_result_count = sum(
            1 for result in top10 if _result_id(result) in sample.irrelevant_result_ids
        )
        total_irrelevant_count += irrelevant_result_count
        returned_result_count += len(results)
        sourced_result_count += len(results) - len(missing_source_result_ids)

        sample_results.append(
            EvaluationSampleResult(
                id=sample.id,
                task=sample.task,
                hit_expected_source=hit_expected_source,
                irrelevant_result_count=irrelevant_result_count,
                missing_source_result_ids=missing_source_result_ids,
                top10_result_sources=[
                    result["source"] for result in top10 if result.get("source")
                ],
            )
        )

    sample_count = len(samples)
    top5_hit_rate = hit_count / sample_count if sample_count else 0.0
    source_completeness = (
        sourced_result_count / returned_result_count if returned_result_count else 1.0
    )
    failed_sample_ids = [
        result.id
        for result in sample_results
        if not result.hit_expected_source or result.missing_source_result_ids
    ]
    passed = (
        top5_hit_rate >= min_top5_hit_rate
        and total_irrelevant_count <= max_top10_irrelevant_result_count
        and source_completeness == 1.0
        and not failed_sample_ids
    )

    return EvaluationReport(
        sample_count=sample_count,
        passed=passed,
        top5_hit_rate=round(top5_hit_rate, 4),
        top10_irrelevant_result_count=total_irrelevant_count,
        source_citation_completeness=round(source_completeness, 4),
        failed_sample_ids=failed_sample_ids,
        samples=sample_results,
    )


def _flatten_context_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for key in (
        "related_code",
        "related_db_schema",
        "related_docs",
        "similar_implementations",
    ):
        values = payload.get(key, [])
        if isinstance(values, list):
            results.extend(value for value in values if isinstance(value, dict))
    return results


def _source_matches_expected(source: Any, expected: ExpectedHit) -> bool:
    if not isinstance(source, dict):
        return False
    expected_source = expected.model_dump(exclude_none=True)
    return all(source.get(key) == value for key, value in expected_source.items())


def _result_id(result: dict[str, Any]) -> str:
    item = result.get("item", {})
    if isinstance(item, dict) and item.get("id"):
        return str(item["id"])
    return "<unknown>"
