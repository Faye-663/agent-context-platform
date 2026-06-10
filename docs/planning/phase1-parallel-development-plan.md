# Phase 1 三人并行开发分工建议

## 适用范围

本文用于指导 Phase 1 基础版 todo 的三人并行开发分工，来源于 `docs/planning/post-mvp-todo.md` 中的 Phase 1 任务拆分。

核心目标不是平均分配任务数量，而是按模块边界分工，减少多人同时修改同一批核心文件造成的冲突。

## Phase 1 目标

Phase 1 的目标是让 ACP 的检索能力变得可评测、可诊断、可解释，并能稳定组装出恰到好处的 agent 上下文。

成功标准：

- 评测任务集可以持续衡量检索质量变化。
- MCP tool contract 更适合中文自然语言任务和代码符号混合检索。
- 开发调试人员可以直接调用 MCP，并看到完整 prompt、response、检索结果与 trace。
- 索引具备 repo 身份、来源、新鲜度与一致性基础。
- 检索可以组合 lexical、vector、symbol 多路召回，并输出可解释 trace。
- context package 能控制 token budget，并表达证据、缺失上下文与置信度。

## 分工原则

- 不按 todo 数量平均分配，按工程边界分配。
- 数据模型和索引一致性优先合入，避免检索层反复追 schema。
- tool contract、retrieval trace、context package schema 需要先对齐，再分别实现。
- `P1-T9: Symbol Index` 拆成两部分：索引/存储由索引负责人实现，retrieval 接入由检索负责人实现。
- 每个分支只绑定一个清晰完成点，避免 Phase 1 大分支。

## 推荐分工

| 开发者 | 主责方向 | Phase 1 Todo | 主要边界 |
|---|---|---|---|
| 开发者 A | 评测、MCP contract、调试入口 | `P1-T1`、`P1-T2`、`P1-T3` | evaluation harness、MCP tool contract、MCP playground、调试展示 |
| 开发者 B | 索引、数据模型、一致性 | `P1-T4`、`P1-T5`、`P1-T6`、`P1-T9` 的索引/存储部分、`P1-T13` | provenance、repo isolation、incremental indexing、symbol catalog、code graph 候选调研 |
| 开发者 C | 检索、召回、上下文组装 | `P1-T7`、`P1-T8`、`P1-T10`、`P1-T11`、`P1-T12`、`P1-T9` 的 retrieval 接入部分 | lexical retrieval、alias mapping、RRF、trace、context composer、sufficiency |

## 任务拆分细节

### 开发者 A：评测与调试入口

主责：

- `P1-T1: Evaluation Harness / Golden Task Set`
- `P1-T2: MCP Tool Contract 优化`
- `P1-T3: MCP Web Playground`

产出边界：

- 定义并实现基础 evaluation case/result 格式。
- 提供可重复运行的基础评测入口。
- 优化四个 MCP tool 的 description、request、response contract。
- 提供轻量 MCP playground，用于开发调试人员直接调用 MCP。
- playground 支持展示完整 prompt、response、检索结果、trace 与 context package。

注意事项：

- A 不负责设计 retrieval ranking 算法，只消费 C 输出的 trace。
- A 不负责改索引数据模型，只消费 B 输出的 provenance、repo identity 和 symbol 字段。
- MCP response 不能把临时实现细节固化为长期公开承诺。

### 开发者 B：索引与数据基础

主责：

- `P1-T4: Index Provenance / Freshness`
- `P1-T5: 多仓共库检索隔离`
- `P1-T6: Incremental Indexing / Index Consistency`
- `P1-T9: Symbol Index` 的索引、存储、清理部分
- `P1-T13: Code Graph Implementation Research`

产出边界：

- 为 indexed item 建立 repo、branch、commit、file hash、index time、index batch 等来源字段。
- 修复多仓共库下的 repo 隔离，避免跨仓污染和覆盖。
- 提供手动 incremental indexing 与一致性清理能力。
- 建立最小 symbol catalog，供 retrieval 层读取。
- 调研代码调用图相关开源项目，产出候选参考，不在 Phase 1 直接引入重型 graph 实现。

注意事项：

- B 不负责 symbol recall 的排序逻辑，只提供稳定的 symbol catalog 读取接口。
- B 的数据模型变更应尽早合入，否则 C 的 retrieval 实现会产生返工。
- provenance 字段需要兼顾后续 context citation、freshness 判断和 multi-repo 扩展。

跨开发者依赖与接口约定：

- B 输出给 A/C 的 `SourceCitation` provenance contract 包括 `branch`、`commit_sha`、`file_hash`、`indexed_at`、`index_batch_id`。
- `branch`、`commit_sha` 是 nullable best-effort 字段；A/C 不能假设它们在非 Git 目录、detached HEAD 或 Git 不可用时一定存在。
- `file_hash`、`indexed_at`、`index_batch_id` 是 `acp-index` 成功写入 item 的索引来源字段，供 A 的 MCP contract / Playground 展示、C 的 trace / context composer / sufficiency 消费。
- A 不另定义 provenance response shape；应直接消费 `SourceCitation` 中的字段。
- C 在 trace、context package 和 sufficiency 中把这些字段当作 provenance 信号，不把缺失 branch / commit 当成索引失败。
- B 的 `P1-T4` 不承诺 repo filter、repo-scoped primary key、旧数据重建、symbol recall、RRF 或 context sufficiency 判断；这些分别归属 `P1-T5`、`P1-T9` retrieval 接入和 C 的检索 / 上下文任务。

### 开发者 C：检索与上下文组装

主责：

- `P1-T7: Lexical Retrieval / Tokenizer / BM25`
- `P1-T8: Domain Vocabulary / Alias Mapping`
- `P1-T10: Retrieval / Multi-Recall / RRF / Trace`
- `P1-T11: Context Composer / Token Budgeting`
- `P1-T12: Context Sufficiency / Confidence`
- `P1-T9: Symbol Index` 的 retrieval 接入部分

产出边界：

- 面向中文自然语言任务和代码符号混合检索，建立 lexical retrieval 基线。
- 建立领域词汇与 alias mapping 的最小可用格式。
- 将 lexical、vector、symbol 多路召回合并，并使用 RRF 做基础融合。
- 输出可解释 trace，支持后续 playground 调试展示。
- 组装 context package，控制 token budget，区分 primary evidence、related context、risks 与 missing context。
- 输出 sufficiency/confidence，标识上下文不足、过期、跨仓风险等信号。

注意事项：

- C 在 symbol catalog 未稳定前，不应假设具体存储结构。
- C 输出的 trace schema 需要提前和 A 对齐。
- context composer 的 response shape 需要和 MCP contract 对齐，避免 A/C 重复修改 API 边界。

## 建议推进顺序

### 第 0 轮：接口对齐

三人共同确认以下最小 contract：

- evaluation case/result schema
- provenance fields
- symbol catalog read API
- retrieval trace schema
- context package schema

本轮只做接口对齐和小范围文档记录，不进入大规模实现。

### 第 1 轮：基础能力并行

开发者 A：

- 实现 `P1-T1` 的基础 evaluation harness。
- 起草 `P1-T2` 的 MCP tool contract。

开发者 B：

- 实现 `P1-T4` 的 provenance 数据基础。
- 实现 `P1-T5` 的 repo identity 和检索隔离基础。

开发者 C：

- 实现 `P1-T7` 的 lexical/BM25 baseline。
- 将 lexical baseline 接入 A 的 evaluation harness。

### 第 2 轮：能力扩展并行

开发者 A：

- 实现 `P1-T3` 的轻量 MCP playground。
- 支持展示当前已有 tool response。

开发者 B：

- 实现 `P1-T6` 的 manual incremental indexing 与一致性清理。
- 开始 `P1-T9` symbol catalog writer。

开发者 C：

- 实现 `P1-T8` alias mapping。
- 实现 `P1-T10` multi-recall、RRF 和 trace。

### 第 3 轮：集成收口

开发者 B：

- 完成 `P1-T9` symbol catalog 的索引/存储/清理。
- 输出稳定的 symbol catalog 读取接口。

开发者 C：

- 接入 symbol recall。
- 完成 `P1-T11` context composer。
- 完成 `P1-T12` context sufficiency/confidence。

开发者 A：

- 将 trace、full prompt、full response、context package 接入 playground。
- 校验 MCP tool contract 与实际 response 是否一致。

## 合并顺序

推荐合并顺序：

1. B 的数据模型、provenance、repo isolation。
2. A 的 evaluation harness 基础能力。
3. C 的 lexical retrieval baseline。
4. B 的 incremental indexing 和 symbol catalog。
5. C 的 multi-recall、RRF、trace、context composer、sufficiency。
6. A 的 MCP playground 展示与 MCP contract 最终同步。

原因：

- 数据模型先稳定，减少 retrieval 和 playground 返工。
- evaluation harness 尽早可用，后续每个检索变更都能被衡量。
- playground 最后吸收 trace 和 context package，避免反复适配半成品 schema。

## 分支建议

推荐使用短分支，不使用一个 Phase 1 大分支：

- `deng/p1-eval-mcp-playground`
- `deng/p1-index-provenance-symbol`
- `deng/p1-retrieval-context`

如果单个分支变更过大，应继续拆成更小 PR，例如：

- `deng/p1-eval-harness`
- `deng/p1-mcp-contract`
- `deng/p1-index-provenance`
- `deng/p1-repo-isolation`
- `deng/p1-lexical-retrieval`
- `deng/p1-rrf-trace`
- `deng/p1-context-composer`

## 冲突控制

高冲突区域：

- API / MCP response schema
- retrieval result model
- indexed item model
- storage schema / migration
- `docs/product/requirements.md`
- `README.md`

控制方式：

- schema 由单一 owner 主改，其他人通过 review 或小 PR 介入。
- retrieval trace schema 由 C 定义、A 消费。
- symbol catalog schema 由 B 定义、C 消费。
- context package schema 由 C 定义、A 消费，A 负责在 MCP/playground 层验证可调试性。
- `requirements.md` 建议由 A 主维护，B/C 只提交对应 task 的最小补充。
- 行为、启动方式、验证方式、配置或公开接口发生变化后，需要执行 docs-sync 检查。

## 不建议的分工方式

不建议按 todo 编号轮流分配，例如 A 负责 `P1-T1` 到 `P1-T4`、B 负责 `P1-T5` 到 `P1-T8`、C 负责 `P1-T9` 到 `P1-T13`。

原因：

- `P1-T4` 到 `P1-T6` 是索引数据基础，拆给不同人会增加 schema 冲突。
- `P1-T7` 到 `P1-T12` 是检索到 context 的连续链路，过度切分会增加接口返工。
- `P1-T2`、`P1-T3` 需要消费 retrieval trace 和 context package，不应该抢先固化最终展示格式。

## 交付检查

每个开发流完成时至少需要满足：

- 任务边界与 `post-mvp-todo.md` 对应。
- 有最小可运行验证。
- 对外 contract 或用户可见行为变化已同步文档。
- 和其他开发流的输入/输出 schema 已明确。
- 没有把 Phase 2 能力提前做成 Phase 1 的重实现。
