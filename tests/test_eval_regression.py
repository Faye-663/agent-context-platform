"""CI 回归门禁：评测样本通过最低阈值。

运行方式：
  ACP_EVAL_API_URL=http://... pytest tests/test_eval_regression.py -v

环境变量：
  ACP_EVAL_API_URL     Context API 地址 (默认 http://127.0.0.1:8000)
  ACP_EVAL_MIN_HIT_RATE 最低 hit rate 阈值 (默认 0.7)
  ACP_EVAL_TOP_K        Top-k 范围 (默认 5)
"""

from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

import pytest

from agent_context_platform.evaluation import (
    load_golden_tasks,
    run_evaluation,
)

API_URL = os.environ.get("ACP_EVAL_API_URL", "http://127.0.0.1:8000")
MIN_HIT_RATE = float(os.environ.get("ACP_EVAL_MIN_HIT_RATE", "0.7"))
TOP_K = int(os.environ.get("ACP_EVAL_TOP_K", "5"))


def _api_available() -> bool:
    """检测 Context API 是否可达。"""
    try:
        urlopen(Request(
            f"{API_URL.rstrip('/')}/search-code",
            data=json.dumps({"query": "test"}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        ), timeout=3)
        return True
    except Exception:
        return False


def test_all_groups_pass_minimum_bar() -> None:
    """所有组的评测样本合在一起，整体通过最低阈值。"""
    if not _api_available():
        pytest.skip(f"Context API not available at {API_URL}")
    tasks = load_golden_tasks("eval/golden-tasks.json")
    group_reports = run_evaluation(
        tasks,
        api_base_url=API_URL,
        top_k=TOP_K,
        min_hit_rate=MIN_HIT_RATE,
    )
    all_pass = all(r.passed for r in group_reports.values())
    failed_ids = [
        s.id
        for r in group_reports.values()
        for s in r.samples
        if not s.hit_expected_source
    ]
    assert all_pass, (
        f"Overall regression failed.\n"
        f"  Failed samples: {failed_ids}"
    )


def test_each_group_passes_individually() -> None:
    """每个组单独通过最低阈值，便于定位薄弱资产类型。"""
    if not _api_available():
        pytest.skip(f"Context API not available at {API_URL}")
    tasks = load_golden_tasks("eval/golden-tasks.json")
    group_reports = run_evaluation(
        tasks,
        api_base_url=API_URL,
        top_k=TOP_K,
        min_hit_rate=MIN_HIT_RATE,
    )
    failures: list[str] = []
    for group_name, report in group_reports.items():
        if not report.passed:
            failures.append(
                f"  {group_name}: hit_rate={report.top_k_hit_rate}, "
                f"MRR={report.mrr}, "
                f"failed={report.failed_sample_ids}"
            )
    assert not failures, (
        f"Groups failed individual threshold:\n" + "\n".join(failures)
    )
