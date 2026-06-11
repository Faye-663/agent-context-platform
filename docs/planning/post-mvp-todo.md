# 后续待办与阶段规划

## 说明

本文记录已经发现、但尚未转入正式需求的工程待办与讨论结论。

文件名 `post-mvp-todo.md` 是历史遗留名称；当前项目按生产级项目维护，不再用 MVP / post-MVP 作为主要边界。后续 TODO 讨论完成后，应把确认后的需求统一转入 `docs/product/requirements.md`。

阶段 0 已完成：MVP 开发与验收。

后续阶段目标围绕一个核心问题展开：提升 ACP 的检索能力，从而为 Coding Agent 提供可信、相关、可引用、恰到好处的工程上下文。

任务编号只表示阶段内任务顺序，不表示全局优先级。正式优先级应在转入 `docs/product/requirements.md` 时单独确认。

## Phase 1：基础版

**阶段目标：** 让 ACP 的检索变得可评测、可诊断、可解释，并能稳定给 Agent 组装恰当上下文。

**阶段验收判断：**

- 有固定评测集和 baseline，可判断检索策略是否真的提升。
- MCP tool contract 稳定，Agent 和 Playground 都能可靠调用。
- 索引结果可追溯到 repo / commit / file hash / index time，不返回明显过期或跨仓污染的证据。
- 中文自然语言任务 + 代码符号混合检索明显优于当前 LIKE + bigram 基线。
- 能输出带 token budget、证据分组、缺失上下文和置信提示的上下文包。

### P1-T1: Evaluation Harness / Golden Task Set

**状态：** 新增，建议最先进入 Phase 1。

**目标：** 建立固定任务集、期望 evidence、指标和报告格式，让后续 BM25、Symbol、RRF、Context Composer 等能力可以被客观比较。

**依赖：** 无。它是多数检索优化的前置依赖。

**被依赖：** `P1-T7`、`P1-T8`、`P1-T9`、`P1-T10`、`P1-T12`、`P2-T1`、`P2-T2`、`P2-T3`。

**待明确：**

- golden task 的数据结构。
- 指标采用 top-k hit rate、MRR、NDCG，还是项目自定义 evidence hit。
- 报告是否需要对比 baseline、分资产类型和分召回通道展示。

### P1-T2: MCP Tool Contract 优化

**状态：** 已转入正式需求；索引 / 存储部分由开发者 B 实施中，retrieval 接入仍归开发者 C。

**目标：** 保留现有 4 个 core tools，优化 description、request format、response format、错误格式和调试语义。

**当前 core tools 判断：**

- `search_code`：按代码资产检索，合理。
- `search_db_schema`：DB schema 的使用场景、过滤条件和 source citation 与代码不同，单独保留合理。
- `search_doc`：文档检索与代码 / schema 不同，单独保留合理。
- `build_task_context`：面向一个任务聚合 code、schema、docs 和 similar implementations，适合作为默认宽检索入口。

**依赖：** 当前 Context API / MCP wrapper 基线。

**被依赖：** `P1-T3`、`P1-T10`、`P1-T11`、`P2-T5`。

**已确认范围：**

- description 要说明适用场景、不适用场景、输入建议、fallback 策略，以及如何处理 `missing_context` 和低相关结果。
- request format 需要可发现、可校验、错误可解释；区分常规参数和高级调试参数。
- response format 要稳定，每条结果保留 source citation、score、score_parts、match_reason。
- 错误格式要区分参数错误、服务不可用、embedding 不可用、检索为空等情况。
- retrieval trace 后续可通过 response 或 debug 输出展示召回通道、原始 rank、融合 rank 和融合解释。

**待明确：**

- `filters` 是继续保留为结构化对象，还是将常用过滤条件提升为显式参数。
- `query_embedding` 是否应从普通 tool contract 中弱化为高级调试参数。
- retrieval trace 应进入正式 response，还是只通过 debug / Playground 暴露。
- 是否需要为 MCP tools 定义版本化 contract。

### P1-T3: MCP Web Playground

**状态：** 已讨论，待转正式需求。

**目标：** 提供轻量 direct MCP client 和 trace viewer，让开发人员不经过 Agent 就能直接调用 MCP tool、观察 request / response、检索命中和调试信息。

**使用链路：**

```text
Human -> Web Playground -> MCP Server -> Context API / Retrieval -> MCP response
```

**依赖：** `P1-T2` 的基础 contract；后续逐步接入 `P1-T10` retrieval trace、`P1-T11` context composer 输出和 `P1-T12` sufficiency 信息。

**被依赖：** `P1-T7`、`P1-T10`、`P2-T5` 的调试和展示。

**已确认范围：**

- 连接本地或指定 MCP Server。
- 列出 MCP tools。
- 允许开发人员手动填写 tool 参数并直接调用 MCP tool。
- 展示完整 MCP request / response JSON。
- 对 `search_code`、`search_db_schema`、`search_doc`、`build_task_context` 等结果做轻量可读化展示。
- 调试模式允许展示敏感信息，包括完整 request、response 和 payload。

**非目标：**

- 不做 Agent workflow replay。
- 不做 LLM 调用平台；v1 不负责展示模型最终回答。
- 不做权限、多租户、审计、复杂报表或正式运营后台。

**待明确：**

- Playground 通过 stdio、streamable-http，还是同时支持两种 MCP transport。
- 是否需要保存调试会话，还是只做一次性调用展示。
- 当前 `TaskContext` 不包含独立 prompt 字段；如需展示完整 prompt，需要先确认 prompt 的生成边界和数据模型。

### P1-T4: Index Provenance / Freshness

**状态：** 新增，待转正式需求。

**目标：** 让每条检索证据都能说明来自哪个 repo、branch / commit、文件版本、索引时间和索引批次，避免 Agent 使用过期或来源不明的上下文。

**依赖：** 当前 `SourceCitation`、`IndexedItem`、`acp-index --repo` 基线。

**被依赖：** `P1-T5`、`P1-T6`、`P1-T9`、`P1-T11`、`P1-T12`、`P2-T4`、`P2-T6`。

**后续成功标准：**

- 检索结果能显示 repo identity、index time 和 source file identity。
- 可判断索引是否对应当前工作区或指定版本。
- 过期、来源不明或跨仓来源可被标记为风险。

**已确认接口边界：**

- provenance 字段进入 `SourceCitation`，包括 `branch`、`commit_sha`、`file_hash`、`indexed_at`、`index_batch_id`。
- `branch` 和 `commit_sha` 是 best-effort Git provenance；非 Git 目录、detached HEAD 或 Git 不可用时允许为空。
- `file_hash`、`indexed_at`、`index_batch_id` 由 `acp-index` 写入，用于后续 freshness 判断、context citation 和调试展示。
- `P1-T4` 不负责 repo 过滤、repo-scoped primary key、旧数据重建、symbol recall、RRF 或 context sufficiency 判断。

**待明确：**

- Agent response 和 debug trace 对 provenance 字段的展示层级。
- 是否需要在后续任务中增加 freshness 风险码或更细粒度 stale 判断。

### P1-T5: 多仓共库检索隔离

**状态：** 已转入正式需求并实施。

**目标：** 避免多个 GitLab code repo 写入同一数据库后互相覆盖、跨仓误召回或污染检索结果。

**当前实现风险：**

- `acp-index --repo` 会写入 `SourceCitation.repo`，但 keyword / vector 检索当前不按 repo 过滤。
- 当前 `IndexedItem.id` 不包含 repo，例如 `code:{path}:{symbol}`、`db_schema:{path}:{table}`、`doc:{path}:{heading_path}`。
- 多 repo 存在相同相对路径和 symbol/table/heading 时，`session.merge` 可能覆盖旧 item。

**依赖：** `P1-T4` 的 repo identity / provenance 设计。

**已确认依赖边界：** `P1-T4` 只提供 provenance contract；`P1-T5` 处理 repo 作为过滤条件、主键组成部分和索引重建边界。

**被依赖：** `P1-T6`、`P1-T9`、`P1-T10`、`P2-T4`、`P2-T6`、`P2-T7`。

**后续成功标准：**

- 调用方可以按 repo 限定 keyword 和 vector 候选集。
- 多 repo 写入同一数据库时，不会因为相同相对路径和 symbol/table/heading 覆盖彼此。
- `SearchResult.source.repo` 继续作为结果来源返回。

**已确认决策：**

- 支持一个数据库保存多个 GitLab code repo。
- `repo` 使用规范化 GitLab code repo identity，例如 `gitlab.example.com/group/project`。
- `indexed_items` 使用 `(repo, id)` 作为存储身份；`item_embeddings` 也按 repo 隔离。
- Context API 支持 `filters.repo`、`constraints.repo`、`ACP_DEFAULT_REPO` 和 `ACP_REQUIRE_REPO_FILTER`。
- 旧索引数据是可重建派生数据，切换 repo-scoped identity 后要求重新执行 `acp-index`。

**非目标：**

- 不处理 doc/code/sql 与 organization 之间的业务归属关系。
- 不处理一篇 doc 适用于多个 repo、一个 DB schema 被多个 repo 使用等跨资产关系。
- 不从 Git remote 自动推断 repo，也不引入 workspace/project 关系模型。

### P1-T6: Incremental Indexing / Index Consistency

**状态：** 已讨论，待转正式需求。

**目标：** 解决代码、文档、SQL 等工程资产变化后，索引如何保持一致；第一阶段先做手动增量索引 + 一致性清理。

**依赖：** `P1-T4`、`P1-T5`。

**被依赖：** `P1-T9`、`P2-T1`、`P2-T6`。

**已确认范围：**

- 开发者显式运行命令触发。
- 支持只重建指定文件或指定 path scope。
- 文件删除、路径移动、symbol 重命名、heading/table 变化后，旧索引必须删除或失效。
- 输出 JSON 摘要，说明 changed、deleted、unchanged、failed。
- 支持 dry-run。
- 与多仓、branch / worktree、repo 隔离边界兼容，不能误删其他 repo 的索引。

**暂缓事项：** watch mode 暂缓到 Phase 2 或更后。

**待明确：**

- 增量索引入口是扩展 `acp-index`，还是新增单独命令。
- 文件变更检测基于 path 参数、manifest、文件 hash，还是 git diff。
- 删除检测如何表达。
- 事务边界是单文件事务、批次事务，还是全量命令事务。

### P1-T7: Lexical Retrieval / Tokenizer / BM25

**状态：** 已讨论，待转正式需求。

**目标：** 升级 keyword / lexical recall 通道，主要服务中文自然语言任务 + 代码符号混合检索。

**当前实现能力判断：**

- 英文 / 代码类 query 当前通过正则抽取 `[a-z0-9_]+` token。
- 中文 query 当前对连续中文片段生成 bigram。
- keyword recall 当前在数据库侧用 `LIKE` 匹配多个字段。
- keyword score 当前在应用侧按 token 命中比例计算。
- 当前没有文档频率、字段权重、长度归一化或 BM25 排序。

**依赖：** `P1-T1`；`P1-T3` 用于调试展示但不是硬依赖。

**被依赖：** `P1-T8`、`P1-T10`。

**已确认范围：**

- 优先支持中文自然语言任务 + 代码符号混合检索。
- 中文分词不能只依赖 bigram；需要可替换的中文分词策略，但避免过早引入重依赖。
- 英文 / 代码 tokenization 需要支持 camelCase、snake_case、qualified symbol、路径片段、错误码等工程 token。
- BM25 作为 lexical retrieval 排序模型，逐步替代当前 LIKE + token 命中比例。
- Playground / retrieval trace 应能展示 tokenization 结果、字段命中和 BM25 / lexical 分数。

**待明确：**

- 中文分词策略：轻量规则、第三方分词库，还是可插拔 provider。
- BM25 在 PostgreSQL 内实现、应用侧实现，还是引入专用搜索组件。
- 不同字段的权重，例如 symbol/title 是否应高于 content/summary。
- tokenization 结果是否需要持久化。

### P1-T8: Domain Vocabulary / Alias Mapping

**状态：** 新增，待转正式需求。

**目标：** 建立业务词、中文表达、代码符号、表名、模块名之间的别名映射，让“支付报文”“订单状态”等中文任务描述能更稳定地召回对应代码和 schema。

**依赖：** `P1-T1`、`P1-T7`；可逐步结合 `P1-T9`。

**被依赖：** `P1-T10`、`P1-T11`、`P1-T12`。

**后续成功标准：**

- 业务词和代码符号/表名之间的映射可被检索使用和 trace 展示。
- alias 命中不会被隐藏成普通 keyword 命中。
- alias 错误或缺失能通过评测集暴露。

**待明确：**

- alias 来源：手工配置、索引时抽取、文档解析，还是后续反馈沉淀。
- alias 存储位置：配置文件、数据库、索引 manifest，还是 metadata。
- alias 是否区分 repo / workspace / domain。

### P1-T9: Symbol Index

**状态：** 已讨论，待转正式需求。

**目标：** 建立轻量 symbol catalog，并提供 symbol recall，作为 keyword / vector 之外的补充召回通道，同时为后续 code graph 铺底。

**当前实现能力判断：**

- Java indexer 已把 `class` 和 `method` 抽取为独立 `IndexedItem`。
- `IndexedItem.source.symbol` 已保存类名或方法名。
- `metadata.symbol_type` 已支持 `class`、`method`、`table`、`column` 等结构化类型。
- `indexed_items.symbol_type` 已建索引，keyword / vector 检索都支持 `filters.symbol_type`。

**依赖：** `P1-T1`、`P1-T4`、`P1-T5`；和 `P1-T6` 在一致性清理上相互约束。

**被依赖：** `P1-T10`、`P2-T1`、`P2-T4`。

**已确认范围：**

- 目标是辅助召回 + code graph 铺底，不是单纯“跳转定义”工具。
- 建立稳定 `symbol_id`、`repo`、`path`、`language`、`kind`、`name`、`qualified_name` 和 source range。
- v1 使用独立 `symbols` 表，不复用 `indexed_items` metadata 作为 catalog 存储。
- v1 覆盖 Java `class`、`interface`、`enum`、`record`、`annotation_type`、`method`、`constructor`、`field`，以及 SQL `table`、`column`；Markdown heading 不纳入 symbol catalog。
- v1 只记录 definitions，不记录 method call、field access、type reference、extends / implements 等 graph edge。
- 开发者 B 提供 exact / prefix lookup；fuzzy、RRF、trace 和 ranking 属于开发者 C。
- 当 query 包含疑似类名、方法名、驼峰词、包路径或完全限定名时，优先召回 exact / prefix / fuzzy 命中的 symbol。
- symbol recall 的结果进入统一 `SearchResult`，并在 `score_parts` 或 trace 中区分 `symbol` 分数。

**待明确：**

- fuzzy 规则范围。
- symbol recall 与 RRF 的融合方式。

### P1-T10: Retrieval / Multi-Recall / RRF / Trace

**状态：** 已讨论，待转正式需求。

**目标：** 建立多路召回框架、RRF 融合和可解释 trace，让 lexical、vector、symbol 等候选可以统一进入候选集并可调试。

**依赖：** `P1-T1`、`P1-T7`、`P1-T8`、`P1-T9`；graph 通道依赖 Phase 2 `P2-T1`。

**被依赖：** `P1-T11`、`P1-T12`、`P2-T1`、`P2-T2`、`P2-T3`。

**已确认范围：**

- 支持 keyword/lexical、vector、symbol，预留 graph 通道。
- 第一阶段融合算法优先采用 RRF，避免直接混合异构 score。
- 每个候选保留召回通道、原始 rank、原始 score、融合后 rank 和融合解释。
- Playground 展示每个候选来自哪些召回通道。

**待明确：**

- 第一阶段 RRF 的 `k` 值、每路召回上限和最终返回上限。
- trace 信息是否只在 debug 模式返回，还是作为 Playground 专用接口返回。
- 固定评测集的数据结构、指标和报告格式。

### P1-T11: Context Composer / Token Budgeting

**状态：** 新增，待转正式需求。

**目标：** 把检索结果组装成适合 Agent 使用的上下文包，解决去重、分组、裁剪、token budget 和主次证据问题。

**依赖：** `P1-T2`、`P1-T8`、`P1-T10`。

**被依赖：** `P1-T12`、`P2-T2`、`P2-T5`。

**后续成功标准：**

- 能区分 primary evidence、related context、background docs、risks、missing_context。
- 能按 token budget 裁剪上下文，避免把“有用但过多”的结果直接塞给 Agent。
- 能去重相同 source、同文件重叠片段和多路召回重复候选。
- 输出结构稳定，可被 MCP tool 和 Playground 展示。

**待明确：**

- token budget 输入来自调用方、默认配置，还是按 tool 固定。
- 不同资产类型的优先级如何定义。
- 是否保留当前 `TaskContext` 模型，还是新增更丰富的 context package。

### P1-T12: Context Sufficiency / Confidence

**状态：** 新增，待转正式需求。

**目标：** 让 ACP 不只返回结果，还能说明上下文是否足够、证据是否新鲜、是否缺少关键资产，以及 Agent 是否应该继续检索或向用户确认。

**依赖：** `P1-T1`、`P1-T4`、`P1-T8`、`P1-T11`。

**被依赖：** `P2-T5`。

**后续成功标准：**

- 能标记低置信度、缺少 code/schema/doc、索引过期、跨仓不可见、召回结果冲突等情况。
- `missing_context` 不只是按资产类型为空判断，而能结合任务和证据质量。
- Agent 可以基于 sufficiency 信息决定继续检索、提问或停止。

**待明确：**

- confidence 是规则输出、评分输出，还是两者结合。
- 哪些 sufficiency 信号进入正式 response，哪些只进 debug trace。
- 是否需要固定错误/风险码。

### P1-T13: Code Graph Implementation Research

**状态：** 已记录，候选参考，未选型。

**目标：** 调研后续实现代码调用图时可参考的开源项目与方案，特别是 `https://github.com/colbymchenry/codegraph`。

**候选参考：**

- `colbymchenry/codegraph`：GitHub public repo，README 将其定位为面向 Claude Code、Codex、Cursor 等 agent 的本地预索引代码知识图 / code intelligence 工具。
- README 显示该项目使用 MIT license，并提供 CLI、agent wiring、project init/index 等使用路径。
- README 声称它提供 symbol relationships、call graphs 和 code structure。

**依赖：** `P1-T9` 的 symbol catalog 边界可以帮助判断输出 schema 是否适配；不依赖运行时代码改动。

**被依赖：** `P2-T1`、`P2-T8`。

**评估维度：**

- License 与商业/生产使用约束。
- Java 支持深度，尤其是 method call、继承、接口实现解析。
- 输出 schema 是否能映射到 ACP 的 symbol catalog 和 graph edge。
- 是否支持本地运行、Windows / CI 环境、增量索引和可重复构建。
- 大型真实工程的性能、准确性和误报率。
- 是否容易嵌入 ACP 当前 `acp-index`、Context API、MCP 和 Playground 调试链路。

## Phase 2：进阶版

**阶段目标：** 在 Phase 1 的评测、trace、symbol、索引一致性和上下文组装稳定后，引入图扩展、重排、路由、多仓关联和反馈闭环。

**阶段验收判断：**

- Code graph 能可靠补充调用方、被调用方、继承/实现上下文。
- Rerank 和 query routing 的收益有评测证据，而不是凭感觉启用。
- 跨仓检索只在显式关系或可靠推断边界内发生。
- Agent 实际使用/忽略的上下文能反馈给评测和排序。

### P2-T1: Code Graph

**状态：** 已讨论，Phase 2 实施。

**目标：** 实现代码图，不扩展为 GraphRAG 或多类型知识图谱；v1 边界为 `contains`、`calls`、`extends` / `implements`。

**依赖：** `P1-T1`、`P1-T6`、`P1-T9`、`P1-T10`、`P1-T13`。

**被依赖：** `P2-T3`、`P2-T4`、`P2-T7`。

**已确认范围：**

- `contains`：file -> class -> method。
- `calls`：method -> method。
- `extends` / `implements`：class -> class / interface。

**暂缓范围：**

- 泛化 `references` 暂缓。
- 不做数据库、文档、API endpoint 与代码之间的知识图谱关系。
- 不把 code graph 直接等同于 ranking 算法。

**待明确：**

- v1 是否只支持 Java。
- `calls` 是否只记录同仓已解析 symbol，还是允许 unresolved external symbol。
- graph 存储是独立表，还是 symbol catalog 的附属表。
- graph recall 与 RRF 的融合方式。

### P2-T2: Rerank

**状态：** 已记录，低优先级，依赖项未满足。

**目标：** 在候选集已足够好的前提下优化最终排序；不能掩盖召回质量不足。

**依赖：** `P1-T1`、`P1-T10`、`P1-T11`。

**后续成功标准：**

- rerank 前后命中率、排序指标和失败案例有可复现实验报告。
- rerank 结果能追溯输入候选、rerank score 和最终排序变化。
- rerank 失败时有明确降级路径，不影响基础检索可用性。

**待明确：**

- 使用本地模型、外部 rerank provider，还是规则/轻量模型。
- rerank 输入是纯文本片段、结构化 citation，还是包含 symbol / graph trace。
- rerank 指标采用 top-k hit rate、MRR、NDCG，还是项目自定义 evidence hit。

### P2-T3: Query Routing

**状态：** 已记录，低优先级，依赖项未满足。

**目标：** 识别 query 类型并影响召回策略；早期应先做 soft routing / debug label，hard routing 需等评测证明收益。

**依赖：** `P1-T1`、`P1-T10`、`P2-T1` 可选。

**后续成功标准：**

- query routing 能解释为什么选择或调整某些召回通道。
- routing 前后检索质量有评测证据。
- 误路由时可通过 trace 定位原因并回退。

**待明确：**

- query 类型体系如何定义。
- routing 是规则驱动、模型驱动，还是混合方式。
- routing 对召回通道是启用/禁用，还是只调整召回上限和融合权重。

### P2-T4: Multi-Repo Relationship Context

**状态：** 已讨论，Phase 2 实施。

**目标：** 在仓库隔离成立的前提下，表达和使用仓库之间的业务/技术关系；第一阶段只做显式配置关系 + 受控跨仓检索。

**依赖：** `P1-T4`、`P1-T5`、`P1-T9` 可选、`P2-T1` 可选。

**已确认范围：**

- 显式配置多仓关系。
- 只有关系配置允许时，才跨 repo 扩展候选。
- 自动从代码、graph 或调用链推断跨仓关系暂缓。

**关系示例：**

- repo A `depends_on` repo B。
- repo A `calls_service` repo B。
- repo A `uses_shared_library` repo B。
- repo A `owns_api`，repo B `consumes_api`。
- repo A 和 repo B 属于同一个 workspace / project。

**待明确：**

- 显式关系配置存放位置：数据库、配置文件，还是索引 manifest。
- 关系是否有方向、类型、权重和有效期。
- 跨仓检索默认关闭还是默认按 workspace 开启。
- 权限、数据保留和跨仓可见性如何约束。

### P2-T5: Retrieval Feedback Loop

**状态：** 新增，Phase 2 实施。

**目标：** 记录 Agent 或开发者实际采纳、忽略、修正的 context/citation，反哺评测、排序和 alias / routing 策略。

**依赖：** `P1-T2`、`P1-T3`、`P1-T11`、`P1-T12`。

**后续成功标准：**

- 能记录哪些 citation 被 Agent 使用、哪些被忽略或判定无关。
- 反馈能关联 query、task、repo、retrieval trace 和最终上下文包。
- 反馈可进入 evaluation dataset 或报告，而不是只留在日志里。

**待明确：**

- 反馈来源是 Playground 人工标注、Agent 自动回传，还是评测脚本记录。
- 是否需要隐私/敏感信息过滤。
- 反馈如何进入 ranking 或 alias 更新流程。

### P2-T6: Watch Mode

**状态：** 已记录，Phase 2 或更后。

**目标：** 在手动增量索引稳定后，再评估是否需要文件监听自动更新索引。

**依赖：** `P1-T4`、`P1-T5`、`P1-T6`。

**暂缓原因：**

- watch mode 会引入并发、抖动、误删、权限、长进程运维和本地开发环境差异问题。
- Phase 1 先用手动增量索引解决索引一致性的核心问题。

**待明确：**

- 是否只面向本地开发环境，还是也用于 CI / server。
- debounce、并发、失败重试和回滚策略。
- watch mode 与 branch/worktree 切换如何交互。

### P2-T7: Automatic Multi-Repo Relationship Inference

**状态：** 新增，Phase 2 以后评估。

**目标：** 在显式多仓关系和 code graph 稳定后，再评估是否从代码调用、依赖文件、API contract 或 graph edge 推断跨仓关系。

**依赖：** `P1-T5`、`P2-T1`、`P2-T4`。

**暂缓原因：**

- 自动推断误报成本高。
- 必须先有 repo identity、symbol identity、API contract 和权限边界。
- 不能把意外跨仓召回误判为有效关联。

**待明确：**

- 可接受的误报率。
- 推断出的关系是否需要人工确认。
- 推断关系是否参与检索，还是只作为建议。

### P2-T8: Code Graph Tool Integration Decision

**状态：** 新增，依赖 Phase 1 调研结论。

**目标：** 基于 `P1-T13` 的调研结论，判断是否直接集成 `colbymchenry/codegraph` 或其他开源工具，还是只参考其数据模型/测试样本。

**依赖：** `P1-T13`、`P2-T1`。

**后续成功标准：**

- 明确候选工具是否可直接集成、仅作参考，或不适合。
- 若选择直接集成，需要补充兼容性、许可、数据模型、验证和迁移成本评估。

**待明确：**

- ACP 是否接受新增运行时依赖。
- 工具输出是否能稳定映射到 ACP symbol catalog 和 graph edge。
- Windows / CI / 大型工程性能是否满足生产级要求。

### P2-T9: Organization / Cross-Asset Relationship Model

**状态：** 新增，后续评估。

**目标：** 在 repo 隔离成立后，单独表达 organization、code repo、DB schema、doc 之间的归属、适用范围和多对多关系，避免把这些语义塞进 `repo` 字段。

**背景发现：**

- 一个 organization 下可能有多个 code repo、多个 DB schema、多篇 doc。
- doc 可能属于某个 code repo，也可能是 organization 级文档，或同时适用于多个 repo。
- DB schema 与 code repo 也可能是一对多、多对多或共享关系。
- `P1-T5` 的 `repo` 只承担 GitLab code repo 隔离键，不表达这些业务关系。

**依赖：** `P1-T5`、`P1-T11`、`P1-T12`、`P2-T4`。

**暂缓原因：**

- 该问题属于关系建模和跨资产检索扩展，早于 `P1-T5` 处理会扩大范围。
- 需要在 repo 隔离、context package、trace 和 sufficiency 稳定后再设计。
- 不能靠 `repo` 字段隐式推断 doc/code/sql 关系。

**待明确：**

- organization / workspace identity 如何定义。
- doc 的适用范围来自显式配置、front matter、目录约定、数据库关系表，还是人工维护。
- DB schema 与 code repo 的关系由配置、导入 manifest、调用链，还是业务系统元数据提供。
- 这些关系何时参与检索扩展，何时只用于 trace / sufficiency 提示。
