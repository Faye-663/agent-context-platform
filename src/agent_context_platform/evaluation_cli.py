from __future__ import annotations

import argparse
import sys

from agent_context_platform.evaluation import (
    format_grouped_reports,
    load_golden_tasks,
    run_evaluation,
)

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="acp-eval",
        description="运行 ACP 检索评测任务集，生成评测报告。",
    )
    parser.add_argument(
        "--tasks",
        required=True,
        help="golden-tasks.json 文件路径",
    )
    parser.add_argument(
        "--api",
        default="http://127.0.0.1:8000",
        help="Context API 地址 (默认: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Top-k 命中范围 (默认: 5)",
    )
    parser.add_argument(
        "--min-hit-rate",
        type=float,
        default=0.7,
        help="最低 hit rate 阈值 (默认: 0.7)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="每条样本的 API 调用超时秒数 (默认: 180)",
    )
    parser.add_argument(
        "--format",
        default="text",
        choices=["text", "markdown", "json"],
        help="报告格式: text / markdown / json (默认: text)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出文件路径 (不传则输出到 stdout)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="仅校验样本文件格式，不调用 Context API",
    )

    args = parser.parse_args()

    # validate-only 模式：只加载并校验文件格式
    if args.validate_only:
        try:
            tasks = load_golden_tasks(args.tasks)
        except ValueError as exc:
            _fail(EXIT_ERROR, str(exc))
        total = sum(len(s) for s in tasks.values())
        print(
            f"valid: {args.tasks} ({len(tasks)} groups, {total} samples)"
        )
        sys.exit(EXIT_PASS)

    # live mode：调 Context API 收集 payload
    try:
        tasks = load_golden_tasks(args.tasks)
    except ValueError as exc:
        _fail(EXIT_ERROR, str(exc))

    group_reports = run_evaluation(
        tasks,
        api_base_url=args.api,
        top_k=args.top_k,
        min_hit_rate=args.min_hit_rate,
        timeout=args.timeout,
    )

    # 格式化输出
    report_text = format_grouped_reports(group_reports, fmt=args.format)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_text)
            f.write("\n")
        print(f"Report saved to: {args.output}", file=sys.stderr)
    else:
        print(report_text)

    # exit code
    all_pass = all(r.passed for r in group_reports.values())
    sys.exit(EXIT_PASS if all_pass else EXIT_FAIL)


def _fail(exit_code: int, message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
