# Phase 1 当前状态汇总

## 结论

截至 2026-06-16，Phase 1 的核心工程链路已经基本合入 `master`。

当前项目已经具备：

- 可重复运行的 evaluation harness 和 golden task 文件。
- 优化后的 Context API / MCP tool contract，支持 `debug_options` 和 `_trace`。
- 轻量 MCP Web Playground。
- repo 级索引隔离、provenance、手动增量索引和 symbol catalog。
- 中文词级 lexical retrieval、alias expansion、lexical / vector / symbol 多路召回和 RRF 融合。
- Context Composer，支持 token budget、missing context、待确认项和 citation 汇总。

当前不建议继续扩大 Phase 1 功能范围。下一步应进入集成验证和效果调优。

## 三人分工完成度

| 开发者 | 职责 | 已合入能力 | 当前完成度 | 剩余事项 |
|---|---|---|---:|---|
| A | Evaluation、MCP contract、Playground | `acp-eval`、`eval/golden-tasks.json`、`debug_options`、简化 `_trace`、`playground/` | 约 85% | 用真实 Context API 跑 live regression；Playground 端到端验证；接入更详细 retrieval trace |
| B | 索引、数据模型、一致性 | provenance、repo-scoped identity、manual incremental indexing、symbol catalog writer / storage / read API | 约 85%-90% | 明确 `source_item_id` 为空的 symbol 是否参与 recall；补齐 code graph 调研结论 |
| C | 检索、召回、上下文组装 | `lexical.py`、`aliases.py`、`retrieval_trace.py`、RRF、symbol recall、`context_composer.py`、中文分词增强 | 约 85% | 将内部 `RetrievalTrace` 暴露给 API / Playground；基于评测调 BM25 / RRF / alias / sufficiency |

## 已合入 PR 对照

| PR | 内容 | 对应职责 |
|---|---|---|
| #17 | 索引来源 provenance | B |
| #18 | multi code repo 共库隔离 | B |
| #19 | `acp-index --path` 手动增量索引 | B |
| #21 | symbol catalog storage | B |
| #22 | P1 retrieval context composition | C |
| #23 | P1 开发者 B 任务状态同步 | B |
| #24 | 中文 lexical segmentation 增强 | C |
| #25 | evaluation harness、MCP contract、Web Playground | A |

## 当前验证

本地全量测试结果：

```text
uv run pytest
130 passed, 2 skipped
```

2 个 skipped 来自 `tests/test_eval_regression.py`，原因是本地没有运行 Context API：

```text
Context API not available at http://127.0.0.1:8000
```

这说明单元测试通过，但 live regression 还需要启动真实 API 和准备真实索引库。

## 当前不足与待完善项

| 待完善项 | 当前影响 | 后续处理 |
|---|---|---|
| `_trace` 仍是 API 层简化汇总 | Playground 只能看到 channel score 摘要，看不到 token、alias、per-channel rank | C 暴露内部 `RetrievalTrace`，A 接入展示 |
| golden tasks 还偏样例化 | 评测指标不能充分代表真实项目效果 | 补 10-20 条真实工程任务，覆盖代码、表、文档、聚合任务 |
| alias 词表仍是 JSON 文件 | 适合 MVP / 早期验证，但缺少 repo / domain 作用域 | 先用 JSON 跑真实任务，再决定是否入库 |
| symbol catalog 粒度大于可展示 IndexedItem 粒度 | 部分 symbol 无法被 retrieval 映射为结果 | 明确 graph-only symbol 和 recall symbol 的边界 |
| Playground 尚未做生产化 UI | 适合开发调试，不适合作为正式产品界面 | 当前定位为调试入口，不包装成管理后台 |

## 推荐下一步

1. 启动 Context API，导入一套真实样例索引，运行 `acp-eval --tasks eval/golden-tasks.json`。
2. 把 C 的内部 trace 接到 API `_trace`，让 Playground 能展示 token、alias、channel rank、RRF。
3. 用真实任务调 BM25 字段权重、RRF 参数、alias 词表和 sufficiency 规则。
4. 明确 P2 是否优先做 code graph、rerank，还是先做多仓关系 / 反馈闭环。
