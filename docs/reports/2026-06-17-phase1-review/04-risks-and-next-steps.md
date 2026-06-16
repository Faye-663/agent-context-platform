# 剩余风险与下一步

## 主要风险

### 1. 评测还没有绑定真实项目数据

当前 `eval/golden-tasks.json` 已经有样例结构，但 live regression 需要真实 Context API 和索引库。

影响：

- 现在能证明框架可跑，不能充分证明真实项目召回质量。

建议：

- 先补 10-20 条真实研发任务。
- 每条任务明确 expected code / schema / doc evidence。
- 用 `acp-eval` 固定跑，避免凭感觉调检索。

### 2. Trace 还不够细

当前 API `_trace` 是从 `SearchResult.score_parts` 汇总出来的简化 trace。

影响：

- Playground 还不能直接解释 tokenization、alias、channel rank 和 RRF 融合细节。

建议：

- C 暴露内部 `RetrievalTrace`。
- A 在 Playground 中展示 query tokens、alias expansions、每路召回 rank、RRF 融合结果。

### 3. Symbol recall 和 code graph 边界需要明确

symbol catalog 覆盖 Java / SQL declarations，但并非每个 symbol 都能映射回可展示的 `IndexedItem`。

影响：

- 当前 retrieval 会跳过 `source_item_id is None` 的 symbol。
- 部分 symbol 更适合作为 code graph 节点，而不是直接召回结果。

建议：

- 明确 recall symbol 和 graph-only symbol 的边界。
- Phase 2 再设计 graph edge，不在 Phase 1 临时扩展。

### 4. Alias 仍是轻量配置

当前 alias 通过 `ACP_ALIAS_FILE` 加载 JSON。

影响：

- 适合 demo 和早期调优。
- 不适合长期维护多 repo / 多 domain 词表。

建议：

- 先基于真实任务沉淀词表。
- 等评测证明收益后，再决定是否入库、是否加 repo / domain scope。

## 推荐 1-2 天工作

1. 启动真实 Context API 和 SQLite / PostgreSQL 索引库。
2. 用一个真实小项目跑 `acp-index`。
3. 补充 10 条真实任务到 `eval/golden-tasks.json` 或单独的临时评测文件。
4. 跑 `acp-eval`，记录 top-k hit rate、MRR、失败案例。
5. 优先修失败案例对应的 alias、tokenization、字段权重。

## 推荐后续 Phase 2 排序

优先级建议：

1. 详细 trace 接入 Playground。
2. 真实数据 evaluation。
3. 检索参数调优。
4. code graph 方案决策。
5. rerank / query routing。
6. 多仓关系模型。

原因：

- trace 和 evaluation 是调优前置条件。
- code graph、rerank、query routing 都需要评测证明收益。
- 多仓关系模型会引入权限和关系维护复杂度，不应过早启动。
