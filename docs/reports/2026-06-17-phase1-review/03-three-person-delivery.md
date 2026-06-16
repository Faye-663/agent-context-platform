# 三人交付对照

## 开发者 A：评测、MCP Contract、Playground

已合入内容：

- `src/agent_context_platform/evaluation.py`
- `src/agent_context_platform/evaluation_cli.py`
- `eval/golden-tasks.json`
- `tests/test_eval_regression.py`
- `debug_options`
- API `_trace`
- `playground/`

对应能力：

- 固定评测集和 MRR / hit rate 报告。
- `acp-eval` CLI。
- MCP tool contract 调整。
- 简化 trace 输出。
- MCP Web Playground。

待完善项：

- live regression 需要真实 Context API。
- `_trace` 还未接入 C 的详细 retrieval trace。
- Playground 需要真实 MCP server 端到端验证。

## 开发者 B：索引、数据模型、一致性

已合入内容：

- `SourceCitation` provenance 字段。
- repo-scoped indexed item / embedding identity。
- `acp-index --path` manual incremental indexing。
- `symbols` catalog。
- Java / SQL symbol writer。
- symbol read API 和清理逻辑。

对应能力：

- 多 repo 共库隔离。
- 索引来源可追溯。
- 文件变更、删除、移动场景可通过 path scope 重建和清理。
- symbol recall 和后续 code graph 有基础数据。

待完善项：

- `source_item_id` 为空的 symbol 是否参与 recall 需要明确。
- code graph 仍是 Phase 2，不在当前实现范围。
- P1-T13 当前只有候选参考记录，需要补正式调研结论。

## 开发者 C：检索、召回、上下文组装

已合入内容：

- `src/agent_context_platform/lexical.py`
- `src/agent_context_platform/aliases.py`
- `src/agent_context_platform/retrieval_trace.py`
- `src/agent_context_platform/context_composer.py`
- `retrieval.py` multi-recall / RRF / symbol recall
- `ACP_ALIAS_FILE`
- `constraints.token_budget`

对应能力：

- 中文词级 lexical retrieval。
- 领域词 alias expansion。
- lexical / vector / symbol 多路召回。
- RRF 融合。
- Context Composer：token budget、missing context、待确认项、citations。

待完善项：

- 将内部 `RetrievalTrace` 正式暴露给 API / Playground。
- 基于真实评测调 BM25 字段权重、RRF 参数和 alias 词表。
- sufficiency / confidence 规则需要从简单规则升级为评测驱动。

## 协作状态

当前三人的主线代码已经合入 `master`，接口边界基本成立：

- B 提供可追溯、可隔离、可增量维护的索引基础。
- C 消费 B 的 symbol catalog 和 provenance，产出检索结果与上下文包。
- A 消费 API / MCP response，提供评测和调试入口。

下一步协作重点是把 C 的详细 trace 接到 A 的 Playground，并用真实索引库跑 A 的 evaluation。
