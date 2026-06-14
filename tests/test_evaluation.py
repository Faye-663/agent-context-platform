from __future__ import annotations

import json

import pytest

from agent_context_platform.evaluation import (
    EvaluationSample,
    ExpectedHit,
    EvaluationReport,
    EvaluationSampleResult,
    evaluate_context_payloads,
    format_grouped_reports,
    format_report,
    load_golden_tasks,
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
    assert report.top_k_hit_rate == 1.0
    assert report.top_k_irrelevant_result_count == 1
    assert report.source_citation_completeness == 1.0
    assert report.samples[0].hit_expected_source is True
    assert report.samples[0].irrelevant_result_count == 1
    assert report.mrr == 0.75  # (1/1 + 1/2) / 2


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
    assert report.top_k_hit_rate == 0.0
    assert report.source_citation_completeness == 0.0
    assert report.samples[0].missing_source_result_ids == ["code:Unknown"]
    assert report.samples[0].first_hit_rank is None


def test_load_golden_tasks_loads_12_samples_in_4_groups() -> None:
    """正常加载 12 条样本，分布在 4 个组。"""
    tasks = load_golden_tasks("eval/golden-tasks.json")

    assert set(tasks.keys()) == {
        "code_search",
        "db_schema_search",
        "doc_search",
        "task_context",
    }
    total_samples = sum(len(samples) for samples in tasks.values())
    assert total_samples == 12
    # 每个样本都有 expected_hits
    for group_samples in tasks.values():
        for sample in group_samples:
            assert isinstance(sample, EvaluationSample)
            assert sample.id
            assert sample.task
            assert len(sample.expected_hits) >= 1


def test_load_golden_tasks_rejects_duplicate_ids(tmp_path) -> None:
    """重复 id 应抛出明确异常。"""
    path = tmp_path / "duplicate-ids.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "groups": {
                    "group_a": {
                        "samples": [
                            {
                                "id": "dup-001",
                                "task": "任务 A",
                                "expected_hits": [
                                    {"source_type": "code", "symbol": "A"}
                                ],
                            },
                            {
                                "id": "dup-001",
                                "task": "任务 B",
                                "expected_hits": [
                                    {"source_type": "code", "symbol": "B"}
                                ],
                            },
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="sample id 重复"):
        load_golden_tasks(path)


def test_load_golden_tasks_rejects_missing_task(tmp_path) -> None:
    """缺少 task 字段应抛出明确异常。"""
    path = tmp_path / "missing-task.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "groups": {
                    "group_a": {
                        "samples": [
                            {
                                "id": "no-task",
                                "expected_hits": [
                                    {"source_type": "code", "symbol": "A"}
                                ],
                            }
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="缺少 task"):
        load_golden_tasks(path)


def test_load_golden_tasks_rejects_missing_expected_hits(tmp_path) -> None:
    """缺少 expected_hits 应抛出明确异常。"""
    path = tmp_path / "missing-hits.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "groups": {
                    "group_a": {
                        "samples": [
                            {
                                "id": "no-hits",
                                "task": "任务 A",
                                "expected_hits": [],
                            }
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="缺少 expected_hits"):
        load_golden_tasks(path)


def test_load_golden_tasks_rejects_wrong_schema_version(tmp_path) -> None:
    """不支持的 schema_version 应抛出明确异常。"""
    path = tmp_path / "wrong-schema.json"
    path.write_text(
        json.dumps(
            {"schema_version": 99, "groups": {}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="不支持的 schema_version"):
        load_golden_tasks(path)


def test_load_golden_tasks_rejects_missing_id(tmp_path) -> None:
    """缺少 id 字段应抛出明确异常。"""
    path = tmp_path / "missing-id.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "groups": {
                    "group_a": {
                        "samples": [
                            {
                                "task": "任务 A",
                                "expected_hits": [
                                    {"source_type": "code", "symbol": "A"}
                                ],
                            }
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="缺少 id"):
        load_golden_tasks(path)


def test_load_golden_tasks_handles_empty_groups(tmp_path) -> None:
    """空组（samples 为空数组）应被跳过，不出现在结果中。"""
    path = tmp_path / "empty-group.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "groups": {
                    "empty_group": {"samples": []},
                    "has_samples": {
                        "samples": [
                            {
                                "id": "sample-1",
                                "task": "任务",
                                "expected_hits": [
                                    {"source_type": "code", "symbol": "A"}
                                ],
                            }
                        ]
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    tasks = load_golden_tasks(path)
    # 空组不出现
    assert "empty_group" not in tasks
    assert "has_samples" in tasks
    assert len(tasks["has_samples"]) == 1


# ---------------------------------------------------------------------------
# MRR + top_k 测试
# ---------------------------------------------------------------------------


def test_mrr_calculation() -> None:
    """3 个样本，命中排名 1、3、未命中，MRR=(1/1+1/3+0)/3=0.444。"""
    samples = [
        EvaluationSample(
            id="mrr-001",
            task="任务 A",
            expected_hits=[ExpectedHit(source_type="code", symbol="A")],
        ),
        EvaluationSample(
            id="mrr-002",
            task="任务 B",
            expected_hits=[ExpectedHit(source_type="code", symbol="B")],
        ),
        EvaluationSample(
            id="mrr-003",
            task="任务 C",
            expected_hits=[ExpectedHit(source_type="code", symbol="C")],
        ),
    ]
    payloads = {
        "mrr-001": {
            "related_code": [
                _result("code:A", {"source_type": "code", "symbol": "A"}),
            ],
            "related_db_schema": [],
            "related_docs": [],
            "similar_implementations": [],
        },
        "mrr-002": {
            "related_code": [
                _result("code:X", {"source_type": "code", "symbol": "X"}),
                _result("code:Y", {"source_type": "code", "symbol": "Y"}),
                _result("code:B", {"source_type": "code", "symbol": "B"}),
            ],
            "related_db_schema": [],
            "related_docs": [],
            "similar_implementations": [],
        },
        "mrr-003": {
            "related_code": [
                _result("code:Z", {"source_type": "code", "symbol": "Z"}),
            ],
            "related_db_schema": [],
            "related_docs": [],
            "similar_implementations": [],
        },
    }

    report = evaluate_context_payloads(samples, payloads)

    assert report.top_k_hit_rate == 0.6667  # 2/3 rounded to 4 decimal places
    assert report.mrr == 0.4444  # (1/1 + 1/3 + 0) / 3
    assert report.samples[0].first_hit_rank == 1
    assert report.samples[1].first_hit_rank == 3
    assert report.samples[2].first_hit_rank is None


def test_top_k_parameter_limits_hit_range() -> None:
    """top_k=3 时排名 4 的命中不计入 hit。"""
    samples = [
        EvaluationSample(
            id="topk-001",
            task="任务",
            expected_hits=[ExpectedHit(source_type="code", symbol="Target")],
        ),
    ]
    payloads = {
        "topk-001": {
            "related_code": [
                _result("code:A", {"source_type": "code", "symbol": "A"}),
                _result("code:B", {"source_type": "code", "symbol": "B"}),
                _result("code:C", {"source_type": "code", "symbol": "C"}),
                _result("code:Target", {"source_type": "code", "symbol": "Target"}),
            ],
            "related_db_schema": [],
            "related_docs": [],
            "similar_implementations": [],
        },
    }

    report = evaluate_context_payloads(samples, payloads, top_k=3)

    assert report.top_k_hit_rate == 0.0
    assert report.samples[0].hit_expected_source is False
    assert report.samples[0].first_hit_rank is None  # rank 4 is outside top-3


def test_top_k_increases_mrr_scope() -> None:
    """top_k=3 时排名 3 命中计入 MRR。"""
    samples = [
        EvaluationSample(
            id="topk-002",
            task="任务",
            expected_hits=[ExpectedHit(source_type="code", symbol="Target")],
        ),
    ]
    payloads = {
        "topk-002": {
            "related_code": [
                _result("code:A", {"source_type": "code", "symbol": "A"}),
                _result("code:B", {"source_type": "code", "symbol": "B"}),
                _result("code:Target", {"source_type": "code", "symbol": "Target"}),
            ],
            "related_db_schema": [],
            "related_docs": [],
            "similar_implementations": [],
        },
    }

    report = evaluate_context_payloads(samples, payloads, top_k=3)

    assert report.top_k_hit_rate == 1.0
    assert report.samples[0].first_hit_rank == 3


# ---------------------------------------------------------------------------
# 报告格式化测试
# ---------------------------------------------------------------------------


def _make_report(passed: bool, hit_rate: float, mrr: float) -> EvaluationReport:
    samples = [
        EvaluationSampleResult(
            id="s-001",
            task="任务一",
            hit_expected_source=True,
            irrelevant_result_count=0,
            missing_source_result_ids=[],
            top_k_result_sources=[{"source_type": "code"}],
            first_hit_rank=2,
        ),
        EvaluationSampleResult(
            id="s-002",
            task="任务二",
            hit_expected_source=False,
            irrelevant_result_count=1,
            missing_source_result_ids=[],
            top_k_result_sources=[],
            first_hit_rank=None,
        ),
    ]
    if not passed:
        samples.append(
            EvaluationSampleResult(
                id="s-003",
                task="任务三",
                hit_expected_source=False,
                irrelevant_result_count=0,
                missing_source_result_ids=["code:Missing"],
                top_k_result_sources=[],
                first_hit_rank=None,
            )
        )
    return EvaluationReport(
        sample_count=len(samples),
        passed=passed,
        top_k_hit_rate=hit_rate,
        top_k_irrelevant_result_count=1,
        mrr=mrr,
        source_citation_completeness=1.0,
        failed_sample_ids=(
            [] if passed else [s.id for s in samples if not s.hit_expected_source]
        ),
        samples=samples,
    )


def test_format_report_text_contains_metrics() -> None:
    report = _make_report(passed=True, hit_rate=0.5, mrr=0.25)
    output = format_report(report, group_name="test", fmt="text")

    assert "Evaluation Report - test" in output
    assert "YES" in output
    assert "0.25" in output


def test_format_report_text_shows_failed() -> None:
    report = _make_report(passed=False, hit_rate=0.33, mrr=0.1667)
    output = format_report(report, group_name="test", fmt="text")

    assert "NO" in output
    assert "Failed samples" in output
    assert "s-002" in output


def test_format_report_markdown_contains_table() -> None:
    report = _make_report(passed=True, hit_rate=0.5, mrr=0.25)
    output = format_report(report, group_name="test", fmt="markdown")

    assert "# Evaluation Report - test" in output
    assert "| Metric | Value |" in output
    assert "| MRR | 0.25 |" in output


def test_format_report_json_contains_data() -> None:
    report = _make_report(passed=True, hit_rate=0.5, mrr=0.25)
    output = format_report(report, group_name="test", fmt="json")

    assert '"group": "test"' in output
    assert '"top_k_hit_rate"' in output
    assert '"mrr"' in output


def test_format_grouped_reports_text_contains_group_table() -> None:
    reports = {
        "code_search": _make_report(passed=True, hit_rate=0.75, mrr=0.5),
        "doc_search": _make_report(passed=False, hit_rate=0.33, mrr=0.1667),
    }
    output = format_grouped_reports(reports, fmt="text")

    assert "ACP Evaluation Report" in output
    assert "code_search" in output
    assert "doc_search" in output
    assert "Failed samples" in output


def test_format_grouped_reports_markdown_contains_overall() -> None:
    reports = {
        "code_search": _make_report(passed=True, hit_rate=1.0, mrr=1.0),
    }
    output = format_grouped_reports(reports, fmt="markdown")

    assert "# ACP Evaluation Report" in output
    assert "## Overall" in output
    assert "## By Group" in output
    assert "code_search" in output


def test_format_grouped_reports_json_has_summary() -> None:
    reports = {
        "code_search": _make_report(passed=True, hit_rate=1.0, mrr=1.0),
    }
    output = format_grouped_reports(reports, fmt="json")

    assert '"code_search"' in output
    assert '"_summary"' in output


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _result(item_id: str, source: dict[str, object] | None) -> dict[str, object]:
    item = {"id": item_id, "title": item_id}
    result: dict[str, object] = {"item": item}
    if source is not None:
        result["source"] = source
    return result
