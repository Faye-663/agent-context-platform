from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field


class ExpectedHit(BaseModel):
    """评测样本期望命中的来源。

    例子：source_type="code", symbol="PaymentMessageBuilder.build"。
    它只用于离线评测，不参与线上检索排序。
    """

    # source_type 对齐 SourceCitation.source_type。
    source_type: str
    # 下面字段按需要填写，评测时会和返回结果的 source 做子集匹配。
    path: str | None = None
    symbol: str | None = None
    table: str | None = None
    column: str | None = None
    heading_path: str | None = None


class EvaluationSample(BaseModel):
    """一条固定评测样本。

    task 会被送进 build-task-context，expected_hits 用来判断 top5 是否召回目标来源。
    """

    # id 用于把样本和实际 API 返回 payload 对齐。
    id: str = Field(min_length=1)
    # task 是模拟 Agent 任务的自然语言描述。
    task: str = Field(min_length=1)
    # expected_hits 至少有一个，否则评测不知道什么算成功。
    expected_hits: list[ExpectedHit] = Field(min_length=1)
    # irrelevant_result_ids 用来标记不应进入 top10 的已知噪声结果。
    irrelevant_result_ids: list[str] = Field(default_factory=list)
    # irrelevant_rules 保留人工说明，不参与当前自动计算。
    irrelevant_rules: list[str] = Field(default_factory=list)
    # notes 记录样本意图，方便以后扩展评测集。
    notes: str | None = None


class EvaluationSampleResult(BaseModel):
    id: str
    task: str
    hit_expected_source: bool
    irrelevant_result_count: int
    missing_source_result_ids: list[str]
    top_k_result_sources: list[dict[str, Any]] = Field(default_factory=list)
    first_hit_rank: int | None = None


class EvaluationReport(BaseModel):
    sample_count: int
    passed: bool
    top_k_hit_rate: float = 0.0
    top_k_irrelevant_result_count: int = 0
    mrr: float = 0.0
    source_citation_completeness: float = 0.0
    failed_sample_ids: list[str] = Field(default_factory=list)
    samples: list[EvaluationSampleResult] = Field(default_factory=list)


def evaluate_context_payloads(
    samples: list[EvaluationSample],
    payloads_by_sample_id: dict[str, dict[str, Any]],
    *,
    min_hit_rate: float = 0.7,
    top_k: int = 5,
    max_irrelevant_result_count: int = 3,
) -> EvaluationReport:
    """基于 Context API 返回 payload 评测检索质量。

    参数：
    - samples：评测样本列表。
    - payloads_by_sample_id：sample id → Context API 返回的 JSON payload。
    - min_hit_rate：最低 top-k hit rate 阈值，低于此值 report.passed=False。
    - top_k：命中检查的前 k 条结果。
    - max_irrelevant_result_count：允许的最大无关结果数。

    指标：
    - top_k_hit_rate：期望证据命中 top-k 的样本比例。
    - mrr：Mean Reciprocal Rank，期望证据首次排名的调和平均倒数。
    - source_citation_completeness：带来源引用结果占比。
    """
    sample_results: list[EvaluationSampleResult] = []
    hit_count = 0
    mrr_sum = 0.0
    returned_result_count = 0
    sourced_result_count = 0
    total_irrelevant_count = 0

    for sample in samples:
        payload = payloads_by_sample_id.get(sample.id, {})
        results = _flatten_context_results(payload)
        top_k_results = results[:top_k]
        # irrelevant 检查使用 2×top_k 范围
        top_wide = results[: top_k * 2]

        hit_expected_source = any(
            _source_matches_expected(result.get("source"), expected)
            for result in top_k_results
            for expected in sample.expected_hits
        )
        if hit_expected_source:
            hit_count += 1

        first_rank = _first_hit_rank(
            results, sample.expected_hits, top_k
        )
        if first_rank is not None:
            mrr_sum += 1.0 / first_rank

        missing_source_result_ids = [
            _result_id(result) for result in results if not result.get("source")
        ]
        irrelevant_result_count = sum(
            1
            for result in top_wide
            if _result_id(result) in sample.irrelevant_result_ids
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
                top_k_result_sources=[
                    result["source"]
                    for result in top_k_results
                    if result.get("source")
                ],
                first_hit_rank=first_rank,
            )
        )

    sample_count = len(samples)
    top_k_hit_rate = hit_count / sample_count if sample_count else 0.0
    mrr = round(mrr_sum / sample_count, 4) if sample_count else 0.0
    source_completeness = (
        sourced_result_count / returned_result_count if returned_result_count else 1.0
    )
    failed_sample_ids = [
        result.id
        for result in sample_results
        if not result.hit_expected_source or result.missing_source_result_ids
    ]
    passed = (
        top_k_hit_rate >= min_hit_rate
        and total_irrelevant_count <= max_irrelevant_result_count
        and source_completeness == 1.0
        and not failed_sample_ids
    )

    return EvaluationReport(
        sample_count=sample_count,
        passed=passed,
        top_k_hit_rate=round(top_k_hit_rate, 4),
        top_k_irrelevant_result_count=total_irrelevant_count,
        mrr=mrr,
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


def _first_hit_rank(
    results: list[dict[str, Any]],
    expected_hits: list[ExpectedHit],
    top_k: int,
) -> int | None:
    """返回任一 expected_hit 在结果列表中首次命中的 1-based 排名。

    未命中 top_k 范围或未命中任何 expected_hit 返回 None。
    """
    for i, result in enumerate(results[:top_k]):
        for expected in expected_hits:
            if _source_matches_expected(result.get("source"), expected):
                return i + 1
    return None


def _result_id(result: dict[str, Any]) -> str:
    item = result.get("item", {})
    if isinstance(item, dict) and item.get("id"):
        return str(item["id"])
    return "<unknown>"


def load_golden_tasks(path: str | Path) -> dict[str, list[EvaluationSample]]:
    """从 JSON 文件加载评测样本集。

    校验流程：
    - 文件存在性
    - JSON 格式正确性
    - schema_version == 1
    - 每组 samples 数组存在
    - 每条样本的 id / task / expected_hits 必填
    - 所有 id 全局唯一

    返回 {group_name: [samples]} 分组结构。
    异常时抛出带中文上下文的 ValueError。
    """
    path = Path(path)
    if not path.exists():
        raise ValueError(f"评测文件不存在: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"评测文件 JSON 格式错误 ({path}): {exc}")

    schema = data.get("schema_version")
    if schema != 1:
        raise ValueError(
            f"不支持的 schema_version: {schema}。当前支持: 1"
        )

    groups = data.get("groups")
    if not isinstance(groups, dict):
        raise ValueError(
            f"评测文件格式错误 ({path}): 缺少 groups 字段或格式不正确"
        )

    result: dict[str, list[EvaluationSample]] = {}
    seen_ids: set[str] = set()

    for group_name, group_data in groups.items():
        if not isinstance(group_data, dict):
            raise ValueError(f"组 '{group_name}' 格式错误: 应为字典")

        samples_raw = group_data.get("samples")
        if not isinstance(samples_raw, list):
            raise ValueError(f"组 '{group_name}' 缺少 samples 数组")

        samples: list[EvaluationSample] = []
        for i, sample_data in enumerate(samples_raw):
            if not isinstance(sample_data, dict):
                raise ValueError(
                    f"组 '{group_name}' 中第 {i + 1} 个样本格式错误: 应为字典"
                )

            sample_id = sample_data.get("id")
            if not sample_id:
                raise ValueError(
                    f"组 '{group_name}' 中第 {i + 1} 个样本缺少 id"
                )
            if not isinstance(sample_id, str):
                raise ValueError(
                    f"组 '{group_name}' 中 id '{sample_id}' 必须是字符串"
                )

            if sample_id in seen_ids:
                raise ValueError(f"sample id 重复: '{sample_id}'")
            seen_ids.add(sample_id)

            if not sample_data.get("task"):
                raise ValueError(f"样本 '{sample_id}' 缺少 task 字段")

            expected_hits_raw = sample_data.get("expected_hits")
            if not expected_hits_raw or not isinstance(expected_hits_raw, list):
                raise ValueError(
                    f"样本 '{sample_id}' 缺少 expected_hits 或不是数组"
                )

            try:
                expected_hits = [
                    ExpectedHit(**hit) for hit in expected_hits_raw
                ]
                sample = EvaluationSample(
                    id=sample_id,
                    task=sample_data["task"],
                    expected_hits=expected_hits,
                    irrelevant_result_ids=sample_data.get(
                        "irrelevant_result_ids", []
                    ),
                    irrelevant_rules=sample_data.get(
                        "irrelevant_rules", []
                    ),
                    notes=sample_data.get("notes"),
                )
            except Exception as exc:
                raise ValueError(f"样本 '{sample_id}' 解析失败: {exc}")

            samples.append(sample)

        if samples:
            result[group_name] = samples

    return result


def run_evaluation(
    tasks: dict[str, list[EvaluationSample]],
    api_base_url: str,
    *,
    top_k: int = 5,
    min_hit_rate: float = 0.7,
    timeout: int = 180,
) -> dict[str, EvaluationReport]:
    """实时模式：调用 Context API 收集 payload 并计算指标。

    对每条样本调用 POST /build-task-context，收集返回 payload，
    然后按组调用 evaluate_context_payloads() 计算指标。

    返回 {group_name: EvaluationReport} 结构。
    单条样本 API 调用失败时记录空 payload，不中断整体评测。
    """
    api_base = api_base_url.rstrip("/")
    payloads: dict[str, dict[str, Any]] = {}

    for group_name, samples in tasks.items():
        for sample in samples:
            try:
                url = f"{api_base}/build-task-context"
                body = json.dumps({"task": sample.task}).encode("utf-8")
                request = Request(
                    url,
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
                with urlopen(request, timeout=timeout) as resp:
                    payloads[sample.id] = json.loads(resp.read())
            except Exception:
                payloads[sample.id] = {}

    group_reports: dict[str, EvaluationReport] = {}
    for group_name, samples in tasks.items():
        group_reports[group_name] = evaluate_context_payloads(
            samples,
            payloads,
            min_hit_rate=min_hit_rate,
            top_k=top_k,
        )

    return group_reports


def format_report(
    report: EvaluationReport,
    group_name: str | None = None,
    fmt: str = "text",
) -> str:
    """将单个 EvaluationReport 格式化为可读文本。

    fmt 支持: text / markdown / json
    group_name 在 text/markdown 格式中用作标题前缀。
    """
    if fmt == "json":
        data = report.model_dump(mode="json")
        if group_name:
            data["group"] = group_name
        return json.dumps(data, ensure_ascii=False, indent=2)

    if fmt == "markdown":
        return _format_report_markdown(report, group_name)

    # default: text
    return _format_report_text(report, group_name)


def format_grouped_reports(
    group_reports: dict[str, EvaluationReport],
    fmt: str = "text",
) -> str:
    """将多组评测报告汇总为一份报告。

    包含总体指标、分组指标和失败样本列表。
    """
    if fmt == "json":
        data = {
            group: report.model_dump(mode="json")
            for group, report in group_reports.items()
        }
        # 追加汇总
        all_samples: list[EvaluationSampleResult] = []
        for report in group_reports.values():
            all_samples.extend(report.samples)
        data["_summary"] = {
            "total_samples": len(all_samples),
            "passed_count": sum(
                1 for r in group_reports.values() if r.passed
            ),
            "failed_sample_ids": [
                s.id for s in all_samples if not s.hit_expected_source
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    if fmt == "markdown":
        return _format_grouped_markdown(group_reports)

    # default: text
    return _format_grouped_text(group_reports)


# ---------------------------------------------------------------------------
# 内部: 文本格式化
# ---------------------------------------------------------------------------


def _format_report_text(
    report: EvaluationReport, group_name: str | None
) -> str:
    header = "Evaluation Report"
    if group_name:
        header = f"{header} - {group_name}"
    lines = [
        "=" * 48,
        header.center(48),
        "=" * 48,
    ]

    passed_label = "YES" if report.passed else "NO"
    hit_info = f"{report.top_k_hit_rate} ({_hit_count(report)}/{report.sample_count})"
    lines.extend(
        [
            f"  Passed:                     {passed_label}",
            f"  Top-K hit rate:             {hit_info}",
            f"  MRR:                        {report.mrr}",
            f"  Irrelevant result count:    {report.top_k_irrelevant_result_count}",
            f"  Source citation completeness: {report.source_citation_completeness}",
        ]
    )

    if report.failed_sample_ids:
        lines.append("  " + "-" * 42)
        lines.append(
            f"  Failed samples: {', '.join(report.failed_sample_ids)}"
        )

    # 列出每个样本的详情
    if report.samples:
        lines.append("  " + "-" * 42)
        lines.append("  Sample details:")
        for sample in report.samples:
            rank_info = (
                f"rank={sample.first_hit_rank}"
                if sample.first_hit_rank is not None
                else "missed"
            )
            hit_mark = "HIT" if sample.hit_expected_source else "MISS"
            lines.append(
                f"    [{hit_mark}] {sample.id}: {sample.task[:40]} "
                f"({rank_info})"
            )

    lines.append("=" * 48)
    return "\n".join(lines)


def _format_grouped_text(
    group_reports: dict[str, EvaluationReport],
) -> str:
    lines = [
        "=" * 60,
        "         ACP Evaluation Report",
        "=" * 60,
    ]

    # 汇总指标
    all_samples: list[EvaluationSampleResult] = []
    total_hit = 0
    total_mrr = 0.0
    total_irrelevant = 0
    total_failed: list[str] = []
    for report in group_reports.values():
        all_samples.extend(report.samples)
        total_irrelevant += report.top_k_irrelevant_result_count
        for s in report.samples:
            if s.hit_expected_source:
                total_hit += 1
            else:
                total_failed.append(s.id)

    sample_count = len(all_samples)
    overall_pass = all(r.passed for r in group_reports.values())
    hit_rate = round(total_hit / sample_count, 4) if sample_count else 0.0
    mrr_sum = sum(
        1.0 / s.first_hit_rank
        for s in all_samples
        if s.first_hit_rank is not None
    )
    overall_mrr = round(mrr_sum / sample_count, 4) if sample_count else 0.0

    passed_label = "YES" if overall_pass else "NO"
    lines.extend(
        [
            f"  Passed:                     {passed_label}",
            f"  Total samples:              {sample_count}",
            f"  Top-K hit rate:             {hit_rate} ({total_hit}/{sample_count})",
            f"  MRR:                        {overall_mrr}",
            f"  Irrelevant result count:    {total_irrelevant}",
        ]
    )

    # 分组表
    if group_reports:
        lines.append("  " + "-" * 56)
        lines.append(
            f"  {'Group':<24s} {'Hit Rate':<14s} {'Passed':<6s}"
        )
        lines.append("  " + "-" * 56)
        for group_name, report in group_reports.items():
            hit_info = f"{report.top_k_hit_rate} ({_hit_count(report)}/{report.sample_count})"
            p_label = "YES" if report.passed else "NO"
            lines.append(
                f"  {group_name:<24s} {hit_info:<14s} {p_label:<6s}"
            )
        lines.append("  " + "-" * 56)

    # 失败样本
    if total_failed:
        lines.append(f"  Failed samples: {', '.join(total_failed)}")

    lines.append("=" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 内部: Markdown 格式化
# ---------------------------------------------------------------------------


def _format_report_markdown(
    report: EvaluationReport, group_name: str | None
) -> str:
    title = f"# Evaluation Report - {group_name}" if group_name else "# Evaluation Report"
    lines = [title, ""]
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    hit_info = f"{report.top_k_hit_rate} ({_hit_count(report)}/{report.sample_count})"
    lines.append(f"| Passed | {'YES' if report.passed else 'NO'} |")
    lines.append(f"| Top-K hit rate | {hit_info} |")
    lines.append(f"| MRR | {report.mrr} |")
    lines.append(f"| Irrelevant result count | {report.top_k_irrelevant_result_count} |")
    lines.append(f"| Source citation completeness | {report.source_citation_completeness} |")
    lines.append("")

    if report.failed_sample_ids:
        lines.append("## Failed samples")
        lines.append("")
        lines.append("| ID | Task | Status |")
        lines.append("|----|------|--------|")
        for s in report.samples:
            if not s.hit_expected_source:
                lines.append(
                    f"| {s.id} | {s.task[:60]} | MISS |"
                )
        lines.append("")

    if report.samples:
        lines.append("## Details")
        lines.append("")
        lines.append("| ID | Task | Hit | First Rank |")
        lines.append("|----|------|-----|------------|")
        for s in report.samples:
            rank_str = str(s.first_hit_rank) if s.first_hit_rank is not None else "-"
            hit_str = "YES" if s.hit_expected_source else "NO"
            lines.append(
                f"| {s.id} | {s.task[:50]} | {hit_str} | {rank_str} |"
            )
        lines.append("")

    return "\n".join(lines)


def _format_grouped_markdown(
    group_reports: dict[str, EvaluationReport],
) -> str:
    lines = ["# ACP Evaluation Report", ""]

    # 汇总
    all_samples: list[EvaluationSampleResult] = []
    total_hit = 0
    total_failed: list[str] = []
    for report in group_reports.values():
        for s in report.samples:
            all_samples.append(s)
            if s.hit_expected_source:
                total_hit += 1
            else:
                total_failed.append(s.id)

    sample_count = len(all_samples)
    hit_rate = round(total_hit / sample_count, 4) if sample_count else 0.0
    mrr_sum = sum(
        1.0 / s.first_hit_rank
        for s in all_samples
        if s.first_hit_rank is not None
    )
    overall_mrr = round(mrr_sum / sample_count, 4) if sample_count else 0.0
    overall_pass = all(r.passed for r in group_reports.values())

    lines.append("## Overall")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Passed | {'YES' if overall_pass else 'NO'} |")
    lines.append(f"| Total samples | {sample_count} |")
    lines.append(f"| Top-K hit rate | {hit_rate} ({total_hit}/{sample_count}) |")
    lines.append(f"| MRR | {overall_mrr} |")
    lines.append("")

    # 分组
    if group_reports:
        lines.append("## By Group")
        lines.append("")
        lines.append("| Group | Hit Rate | MRR | Passed |")
        lines.append("|-------|----------|-----|--------|")
        for group_name, report in group_reports.items():
            hit_info = f"{report.top_k_hit_rate} ({_hit_count(report)}/{report.sample_count})"
            p_label = "YES" if report.passed else "NO"
            lines.append(
                f"| {group_name} | {hit_info} | {report.mrr} | {p_label} |"
            )
        lines.append("")

    # 失败
    if total_failed:
        lines.append("## Failed Samples")
        lines.append("")
        for s in all_samples:
            if not s.hit_expected_source:
                lines.append(f"- **{s.id}**: {s.task}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 内部: 辅助
# ---------------------------------------------------------------------------


def _hit_count(report: EvaluationReport) -> int:
    """报告中的命中样本数。"""
    return sum(1 for s in report.samples if s.hit_expected_source)
