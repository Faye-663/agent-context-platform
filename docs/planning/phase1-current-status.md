# Phase 1 当前状态与验收缺口

## 验收结论

截至 2026-06-23，Phase 1 的基础实现已合入 `master`，但原始需求尚未 100% 完成，不能标记为“Phase 1 已验收完成”。

`P1-T5`（多仓共库隔离）和 `P1-T6`（手动增量索引与一致性清理）已具备实现和自动化测试证据。其余任务多数已具备基础实现，但仍有原始成功标准、公开调试链路或真实项目验证缺口。

这里的未完成项属于已确认的 Phase 1 原始范围，不应以“后续扩大功能范围”处理。

## 当前验证证据

- 2026-06-23 本地执行 `uv run pytest`：`132 passed, 2 skipped`。
- 两个 skipped 均来自 `tests/test_eval_regression.py`：未启动真实 Context API，因而没有连接真实索引库。
- `uv run acp-eval --tasks eval/golden-tasks.json --validate-only` 通过：当前任务集有 4 组、12 条样例。
- 尚无真实项目索引上的 live evaluation、baseline 对比结果或可复现失败案例报告；因此无法证明中文自然语言与代码符号混合检索优于早期 LIKE 基线。

## 原始任务完成度

| 任务 | 当前判断 | 已有能力 | 未完成或不符项 |
|---|---|---|---|
| P1-T1 Evaluation Harness | 部分完成 | 固定任务格式、指标、`acp-eval` 和回归入口 | 无真实项目 baseline、对比产物和 live 评测证据 |
| P1-T2 MCP Tool Contract | 部分完成 | 四个 core tools、`debug_options`、错误 envelope | `_trace` 不完整；空检索没有约定的可区分状态 |
| P1-T3 MCP Web Playground | 部分完成 | HTTP 调用、工具列表、参数表单、可读化结果 | 不展示完整 MCP wire request/response；尚无端到端验证；存在未修复的 DOM XSS 风险 |
| P1-T4 Provenance / Freshness | 部分完成 | repo、Git best-effort、file hash、索引时间和批次写入 citation | 无当前工作区或指定版本的 stale 判断，也没有 freshness risk code |
| P1-T5 多仓共库隔离 | 已实现 | repo-scoped item / embedding identity 和 repo filter | 未发现原始范围内的直接缺口 |
| P1-T6 Incremental Indexing | 已实现 | `--path`、dry-run、file hash、范围清理和失败文件保留 | 未发现原始范围内的直接缺口 |
| P1-T7 Lexical / BM25 | 部分完成 | 中文分词、工程 token 和 BM25-like 字段加权 | token、字段命中和 lexical 细节未进入 API / Playground trace |
| P1-T8 Alias Mapping | 部分完成 | JSON alias 配置和 query expansion | alias expansion 仅在内部 trace；评测集未覆盖 alias 错误或缺失 |
| P1-T9 Symbol Index | 部分完成 | catalog、索引、清理、exact / prefix lookup 和 symbol recall | `source_item_id is None` 的 catalog symbol 会被 recall 跳过，覆盖边界未决 |
| P1-T10 Multi-Recall / RRF / Trace | 部分完成 | lexical / vector / symbol、RRF 和内部 `RetrievalTrace` | API `_trace` 缺少 query token、alias、channel rank 和完整融合解释 |
| P1-T11 Context Composer | 未达标 | token budget、citation 汇总和基础风险提示 | 未区分 primary / related / background evidence；不去重相同 source、重叠片段或跨分组重复候选 |
| P1-T12 Sufficiency / Confidence | 未达标 | 空资产类型、低分和缺 provenance 的基础提示 | `missing_context` 仍主要按资产类型为空判断；无 stale、跨仓不可见、结果冲突等信号 |
| P1-T13 Code Graph Research | 未完成 | 已记录候选参考 | 未形成正式选型、兼容性和验证结论 |

## 阶段验收前必须关闭的事项

1. 在真实项目数据上建立可重复 baseline，并记录 `acp-eval` 的 top-k hit rate、MRR 和失败案例。
2. 将内部 `RetrievalTrace` 无损序列化到 debug response，并在 Playground 展示 token、alias、channel rank 和 RRF 信息。
3. 修复 Context Composer 的跨分组重复候选问题，定义证据层级，并补充相应自动化测试。
4. 定义并实现 stale、跨仓可见性和结果冲突的 sufficiency / freshness 判断；再决定结构化 confidence 与 risk code 的公开契约。
5. 修复 Playground 对 MCP response 和索引内容使用 `innerHTML` 的 DOM XSS 风险，并完成真实 MCP Server 端到端验证。
6. 完成 P1-T13 的 code graph 候选调研结论，明确直接集成、仅作参考或不采用。

## 文档职责

- [后续待办与阶段规划](post-mvp-todo.md) 保留 Phase 1 原始任务边界和 Phase 2 待办。
- 本文是当前实现与验收缺口的唯一状态入口。
- README、架构设计和 Context API 文档只描述当前已实现的运行行为与公开契约，不将未完成项表述为既定能力。
