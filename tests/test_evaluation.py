from __future__ import annotations

from agent_context_platform.evaluation import (
    EvaluationSample,
    ExpectedHit,
    evaluate_context_payloads,
)


def test_evaluation_calculates_top5_hit_and_source_completeness() -> None:
    samples = [
        EvaluationSample(
            id="mvp-sample-001",
            task="新增支付接口",
            expected_hits=[
                ExpectedHit(
                    source_type="code",
                    path="src/main/java/example/PaymentMessageBuilder.java",
                    symbol="PaymentMessageBuilder.build",
                )
            ],
            irrelevant_result_ids=["code:AccountQueryService.query"],
            irrelevant_rules=["账户查询实现不属于支付报文生成链路。"],
        ),
        EvaluationSample(
            id="mvp-sample-002",
            task="补退款状态表字段",
            expected_hits=[ExpectedHit(source_type="db_schema", table="refund_order")],
            irrelevant_result_ids=[],
            irrelevant_rules=[],
        ),
    ]
    payloads = {
        "mvp-sample-001": {
            "related_code": [
                _result(
                    "code:AccountQueryService.query",
                    {
                        "source_type": "code",
                        "path": "src/main/java/example/AccountQueryService.java",
                        "start_line": 1,
                        "end_line": 12,
                        "symbol": "AccountQueryService.query",
                    },
                ),
                _result(
                    "code:PaymentMessageBuilder.build",
                    {
                        "source_type": "code",
                        "path": "src/main/java/example/PaymentMessageBuilder.java",
                        "start_line": 10,
                        "end_line": 30,
                        "symbol": "PaymentMessageBuilder.build",
                    },
                ),
            ],
            "related_db_schema": [],
            "related_docs": [],
            "similar_implementations": [],
        },
        "mvp-sample-002": {
            "related_code": [],
            "related_db_schema": [
                _result(
                    "db_schema:refund_order",
                    {"source_type": "db_schema", "table": "refund_order"},
                )
            ],
            "related_docs": [],
            "similar_implementations": [],
        },
    }

    report = evaluate_context_payloads(samples, payloads)

    assert report.sample_count == 2
    assert report.top5_hit_rate == 1.0
    assert report.top10_irrelevant_result_count == 1
    assert report.source_citation_completeness == 1.0
    assert report.samples[0].hit_expected_source is True
    assert report.samples[0].irrelevant_result_count == 1


def test_evaluation_reports_failed_samples_and_missing_sources() -> None:
    samples = [
        EvaluationSample(
            id="mvp-sample-001",
            task="新增支付接口",
            expected_hits=[
                ExpectedHit(
                    source_type="code",
                    path="src/main/java/example/PaymentMessageBuilder.java",
                    symbol="PaymentMessageBuilder.build",
                )
            ],
            irrelevant_result_ids=[],
            irrelevant_rules=[],
        )
    ]
    payloads = {
        "mvp-sample-001": {
            "related_code": [_result("code:Unknown", None)],
            "related_db_schema": [],
            "related_docs": [],
            "similar_implementations": [],
        }
    }

    report = evaluate_context_payloads(samples, payloads)

    assert report.passed is False
    assert report.top5_hit_rate == 0.0
    assert report.source_citation_completeness == 0.0
    assert report.samples[0].missing_source_result_ids == ["code:Unknown"]


def _result(item_id: str, source: dict[str, object] | None) -> dict[str, object]:
    item = {"id": item_id, "title": item_id}
    result: dict[str, object] = {"item": item}
    if source is not None:
        result["source"] = source
    return result
