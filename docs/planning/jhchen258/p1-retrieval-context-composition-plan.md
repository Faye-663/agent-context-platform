# P1 检索与上下文组装技术方案

## 状态

首版代码已实现，待评审和参数调优。

## 个人开发边界

本文是开发者 C 的个人方案文档，描述检索与上下文组装方向的技术设计、改动影响、协作边界和冲突风险。首版实现已按本文边界落到代码中，后续 review 重点应放在召回效果、参数调优和是否需要暴露 trace API。

开发者 C 负责完整交付以下能力：

- `P1-T7: Lexical Retrieval / Tokenizer / BM25`
- `P1-T8: Domain Vocabulary / Alias Mapping`
- `P1-T10: Retrieval / Multi-Recall / RRF / Trace`
- `P1-T11: Context Composer / Token Budgeting`
- `P1-T12: Context Sufficiency / Confidence`
- `P1-T9: Symbol Index` 的 retrieval 接入部分

本方案不再把开发者 C 的工作拆成多个交付阶段。Phase 1 的分工已经按 A/B/C 三个人拆开，开发者 C 应在自己的开发分支中完成上述完整能力。后续可以保留一个调优阶段，用于调整 BM25 参数、字段权重、alias 词表、RRF 参数和 sufficiency 阈值。

不负责范围：

- 不负责 evaluation harness 和 MCP playground 的主体实现。
- 不负责 indexer、provenance、repo scoped identity、incremental indexing 和 symbol catalog 的写入。
- 不负责数据库 schema 的主导设计，除非后续和开发者 B 对齐后确实需要 retrieval 辅助表。
- 不负责 code graph / GraphRAG / rerank 模型接入。

首版实现位置：

| 文件 | 实现内容 |
|---|---|
| `src/agent_context_platform/lexical.py` | 工程 tokenization、中文 bigram fallback、BM25-like lexical scoring |
| `src/agent_context_platform/aliases.py` | 轻量领域词 alias 配置和 query expansion |
| `src/agent_context_platform/retrieval_trace.py` | 多路召回 hit、RRF 融合候选和内部 trace 结构 |
| `src/agent_context_platform/retrieval.py` | lexical / vector / symbol 多路召回、RRF 融合、score_parts 和 match_reason |
| `src/agent_context_platform/context_composer.py` | token budget、missing context、risk 和 citation 汇总 |
| `src/agent_context_platform/context_builder.py` | 四类上下文检索编排，并接入 ContextComposer |
| `src/agent_context_platform/runtime.py` | 可选 `ACP_ALIAS_FILE` 运行时配置 |
| `tests/test_lexical.py`、`tests/test_retrieval.py`、`tests/test_context_api.py`、`tests/test_runtime.py` | 首版行为回归测试 |

## 背景

当前检索链路是：

```text
Context API
  -> TaskContextBuilder
  -> HybridSearchService
  -> IndexedItemRepository
  -> indexed_items / item_embeddings
```

当前实现已经可以跑通基础检索和 `build-task-context`，但还停留在 MVP 基线：

- keyword recall 主要依赖 SQL `LIKE`。
- query tokenization 主要是英文正则和中文 bigram。
- keyword score 主要按 token 命中比例计算。
- keyword 和 vector 分数直接按固定权重混合。
- 还没有稳定的多路召回框架。
- 还没有 RRF 融合。
- 还没有可解释 retrieval trace。
- `TaskContextBuilder` 只是把 code、db schema、docs、similar implementations 分别搜出来后拼装，没有 token budget、证据优先级、上下文充分性判断。

Phase 1 的目标不是引入一个重型搜索系统，而是在现有架构上把检索变得可评测、可诊断、可解释，并能稳定组装给 Coding Agent 使用的上下文包。

## 总体方案

开发者 C 的完整交付方案是：

```text
用户任务 / Agent 查询
  -> Query normalization
  -> Tokenization
  -> Alias expansion
  -> 多路召回
       lexical / BM25
       vector / pgvector
       symbol recall
  -> RRF 融合
  -> Retrieval trace
  -> Context composer
       evidence 分组
       去重
       token budget
       citation 汇总
  -> Sufficiency / confidence
  -> TaskContext 返回
```

核心原则：

- 保留 `Context API -> TaskContextBuilder -> HybridSearchService -> Repository` 的主链路，不另起一套检索入口。
- 不让 MCP 直接访问数据库或 retrieval 内部逻辑，MCP 仍然只调用 Context API。
- 检索结果必须保留 `SourceCitation`，不能返回无来源上下文。
- 多路召回的融合使用 RRF，不直接把 lexical、vector、symbol 的原始分数混在一起。
- `retrieval trace` 要能解释结果从哪个通道召回、原始排名是多少、RRF 如何贡献、为什么最终进入上下文。
- `context composer` 要控制上下文规模，不能简单把所有 top-k 原样塞给 Agent。
- `sufficiency/confidence` 先用规则判断，不引入 LLM 判断。

## 完整交付内容

### 1. Lexical Retrieval / Tokenizer / BM25

把当前简单 token 命中比例升级为更适合工程检索的 lexical scoring。

重点支持：

- 中文自然语言任务。
- 英文关键词。
- Java 类名 / 方法名。
- camelCase / PascalCase。
- snake_case / kebab-case。
- package / fully qualified symbol。
- 文件路径片段。
- 表名、字段名、错误码、状态码等工程 token。

建议新增模块：

```text
src/agent_context_platform/lexical.py
```

职责：

- query tokenization。
- indexed item 字段 tokenization。
- 字段权重计算。
- BM25 或 BM25-like scoring。
- 返回 lexical score、命中 token、命中字段等解释信息。

中文分词建议：

- 轻量规则分词。
- 领域词表最长匹配。
- 中文 bigram fallback。

本次实现不建议直接引入重型中文分词依赖。原因是当前还需要通过 evaluation harness 证明检索改进有效，过早引入复杂依赖会提高部署和调试成本。

字段权重建议：

| 字段 | 权重倾向 | 原因 |
|---|---|---|
| `source.symbol` | 高 | 类名 / 方法名对代码检索最关键 |
| `title` | 高 | 当前索引项标题通常是最浓缩的语义 |
| `source.table` / `source.column` | 高 | DB schema 检索核心字段 |
| `source.heading_path` | 高 | Markdown 文档章节定位关键 |
| `summary` | 中 | 摘要有语义但可能泛化 |
| `content` | 中低 | 内容长，噪声更大 |
| `metadata` | 中 | 结构化补充字段 |
| `source.path` | 低到中 | 路径有模块线索，但不能过度放大 |

### 2. Domain Vocabulary / Alias Mapping

增加领域词和工程资产之间的映射，让中文业务表达可以稳定召回代码、表结构和文档。

建议新增模块：

```text
src/agent_context_platform/aliases.py
```

本次实现中，alias 来源建议使用轻量配置，不进入数据库。

示例：

```json
{
  "aliases": [
    {
      "term": "现金流审批",
      "expands_to": [
        "cashflow approval",
        "PaymentApprovalService",
        "payment_approval"
      ]
    }
  ]
}
```

设计要求：

- alias expansion 必须进入 retrieval trace。
- alias 命中不能隐藏成普通 keyword 命中。
- alias 配置应允许后续扩展 repo / domain 作用域，但本次交付不强制实现复杂作用域模型。
- alias 错误或缺失应能通过 evaluation case 暴露。

### 3. Multi-Recall / RRF / Trace

建立多路召回框架，让 lexical、vector、symbol 召回都能进入统一候选池，并通过 RRF 融合。

召回通道：

| 通道 | 说明 |
|---|---|
| `lexical` | BM25 lexical recall |
| `vector` | 已有 embedding / pgvector recall |
| `symbol` | symbol exact / prefix / lightweight fuzzy recall |
| `graph` | 预留给后续 code graph，不在本次交付实现 |

RRF 参数建议：

```text
rrf_k = 60
per_channel_limit = max(final_limit * 3, 20)
```

候选去重身份必须使用：

```text
(repo, item_id)
```

不能只按 `item.id` 去重。原因是 P1-T5 repo scoped identity 合入后，同一个 `id` 只在单个 repo 内唯一。

建议新增模块：

```text
src/agent_context_platform/retrieval_trace.py
```

trace 至少记录：

- 原始 query。
- query tokens。
- alias expansions。
- recall channel。
- channel raw rank。
- channel raw score。
- RRF contribution。
- final rank。
- final score。
- matched fields。
- source provenance。

trace 是否默认进入正式 API response，需要和开发者 A 对齐。开发者 C 应提供稳定内部 trace 结构，并支持 API / Playground 后续消费。

### 4. Symbol Index Retrieval 接入

开发者 B 负责 symbol catalog 的索引、存储和清理。开发者 C 负责把 symbol recall 接入检索融合链路。

在开发者 B 的 symbol catalog read API 稳定前，开发者 C 不应假设具体表结构。

可先用现有 indexed item 字段实现轻量 symbol recall：

- `source.symbol`
- `title`
- `metadata.symbol_type`
- `source.table`
- `source.column`
- `source.heading_path`

等 B 输出稳定 symbol catalog read API 后，再替换 symbol recall 的底层数据源。

Symbol recall 的结果必须进入统一 `SearchResult`，并在 `score_parts` 或 trace 中区分 `symbol` 贡献。

### 5. Context Composer / Token Budgeting

把当前简单的 `TaskContextBuilder` 升级为真正适合 Agent 使用的上下文组装层。

建议新增模块：

```text
src/agent_context_platform/context_composer.py
```

职责：

- 对检索结果做去重。
- 同文件相邻或重叠片段裁剪。
- 按资产类型和分数选择 primary evidence。
- 区分 primary evidence、related context、background docs、risks、missing context。
- 控制 token budget。
- 汇总 citations。
- 保证返回结果都有 citation。

建议在 `build-task-context` 的 `constraints` 中支持可选参数：

```json
{
  "constraints": {
    "language": "java",
    "repo": "gitlab.example.com/group/project",
    "token_budget": 4000
  }
}
```

本次实现使用近似 token 估算，不绑定具体模型 tokenizer。原因是不同 Agent / LLM tokenizer 不同，Phase 1 重点是避免上下文无限膨胀，不是精确 token 计费。

### 6. Context Sufficiency / Confidence

让 ACP 不只返回检索结果，还能说明上下文是否足够、证据是否可靠、是否需要继续检索或人工确认。

本次实现建议用规则输出，不引入模型判断。

可判断信号：

- code / db_schema / doc 是否缺失。
- top result 分数是否过低。
- citation 是否完整。
- repo 是否缺失或不一致。
- `indexed_at` 是否缺失。
- `file_hash` 是否缺失。
- top evidence 是否集中在单一弱来源。
- alias expansion 是否完全没有命中。
- 召回结果是否存在明显冲突。

输出建议：

- 继续复用现有 `risks` 和 `missing_context`。
- 新增结构化 `sufficiency` / `confidence` 字段需要和开发者 A 的 MCP contract 对齐后再确定。
- 即使暂时不把完整结构暴露给 API，也应在内部 context composer 中形成稳定判断逻辑，便于后续展示和评测。

## 对代码库的影响

| 文件 / 模块 | 影响程度 | 开发者 C 改动内容 | 冲突风险 |
|---|---|---|---|
| `src/agent_context_platform/retrieval.py` | 高 | 从固定加权检索改为 lexical / vector / symbol 多通道召回、RRF 融合和 trace 生成 | 高，开发者 B 的 repo filter / symbol 接入也会改这里 |
| `src/agent_context_platform/context_builder.py` | 高 | 从简单拼装改为调用 `ContextComposer` 组装任务上下文 | 高，开发者 B 的 repo constraints、开发者 A 的 contract 调整都可能改这里 |
| `src/agent_context_platform/models.py` | 中 | 可能新增 trace、context package、sufficiency 相关模型或字段 | 高，A 会关心 MCP/API response，B 会关心 provenance / symbol identity |
| `src/agent_context_platform/api.py` | 中 | 可能增加 `include_trace`、`constraints.token_budget`、sufficiency 输出 | 高，A/B 都可能改 API contract 和 repo filter |
| `src/agent_context_platform/storage.py` | 中 | 可能新增 coarse lexical candidate、symbol candidate helper | 高，B 对 storage schema 和 repo scoped identity 有主责改动 |
| `src/agent_context_platform/mcp_server.py` | 小到中 | 不复制 retrieval 逻辑，只跟随 Context API contract 暴露 trace / sufficiency | 中，A 会主改 MCP tool contract |
| `tests/test_retrieval.py` | 高 | 增加 lexical、alias、RRF、trace、symbol recall 测试 | 中，B repo isolation 测试也可能改检索测试 |
| `tests/test_context_api.py` | 中 | 增加 token budget、trace、sufficiency 相关 API 测试 | 高，A/B 也可能改 API 测试 |
| `docs/api/context-api.md` | 中 | 如新增公开字段，需要同步 API 文档 | 高，A/B 都会改公开 contract |
| `docs/architecture/design.md` | 中 | 同步 retrieval/context composer 架构变化 | 中 |
| `docs/product/requirements.md` | 小到中 | 若能力转正式需求，需要补充检索与上下文要求 | 中 |

## 代码冲突风险说明

开发者 C 的改动不是孤立新增模块。虽然可以通过新增 `lexical.py`、`aliases.py`、`retrieval_trace.py`、`context_composer.py` 降低冲突，但接入点必然涉及现有核心文件。

主要冲突来源：

1. 开发者 A 会修改 MCP contract、Context API response、playground 展示和 evaluation harness。开发者 C 的 trace、sufficiency、context package 会影响这些 contract。
2. 开发者 B 会修改 repo scoped identity、repo filter、storage schema、symbol catalog 和 incremental indexing。开发者 C 的候选去重、symbol recall、freshness 判断依赖这些字段和接口。
3. `retrieval.py`、`context_builder.py`、`api.py`、`models.py` 是 A/B/C 都可能接触的高冲突区域。
4. 如果 PR #18 的 repo scoped identity 尚未合入，开发者 C 不能按旧的 `item.id` 逻辑固化候选身份，否则后续会返工。

冲突控制建议：

- 开发前先基于最新 `master`，并确认 P1-T5 repo isolation 是否已合入。
- 如果 P1-T5 未合入，开发者 C 代码中应预留 `(repo, id)` 候选身份，不写死只按 `id` 去重。
- `models.py` 和 `api.py` 的公开字段变更应先和开发者 A 对齐。
- `storage.py` 的 schema 变更应避免由 C 主导；如必须新增 repository helper，应尽量不改表结构。
- `retrieval.py` 内部可以先定义私有 trace/candidate 对象，避免过早冻结 API contract。
- 公共文档如 `docs/api/context-api.md`、`docs/product/requirements.md` 应在 contract 确认后再集中更新。

## 替代方案

### 方案 A：直接使用 PostgreSQL Full Text Search

优点：

- 可以把部分排序下推到数据库。
- 大数据量下可能更快。

缺点：

- 中文分词、代码符号拆分仍然需要自定义。
- SQLite 测试路径会和生产路径差异变大。
- 需要较早绑定 PostgreSQL 特性。

结论：

不建议作为本次主方案。可以作为后续性能优化或搜索质量调优方向。

### 方案 B：引入独立搜索引擎

例如 Elasticsearch / OpenSearch / Meilisearch。

优点：

- 搜索能力成熟。
- BM25、字段权重、Analyzer 都比较完整。

缺点：

- 引入新基础设施。
- 增加部署、同步、一致性和运维成本。
- 超出当前 Phase 1 轻量化目标。

结论：

不建议 Phase 1 引入。除非后续评测证明现有数据库 + 应用侧排序无法满足需求。

### 方案 C：索引阶段持久化 tokens

优点：

- 查询时更快。
- trace 更稳定。

缺点：

- 需要 schema 设计。
- 需要重建索引。
- 和开发者 B 的 index consistency / incremental indexing 耦合。

结论：

不作为本次主方案。先用应用侧 tokenization 验证效果，再决定是否持久化。

### 方案 D：所有 API 默认返回完整 trace

优点：

- 调试方便。
- Playground 展示方便。

缺点：

- response 变大。
- 可能暴露 query/task 全文和内部评分细节。
- 过早固化公开 contract。

结论：

不建议默认返回。先支持 debug-only 或 playground-only，再和开发者 A 对齐正式 contract。

## 与其他开发者的协作边界

### 与开发者 A

需要对齐：

- trace 是否进入正式 response。
- Playground 如何展示 token、alias、channel rank、RRF 和 context package。
- evaluation harness 如何衡量 lexical / RRF / context composer 的收益。
- MCP tool 是否增加 `include_trace`、`token_budget` 等参数。

开发者 C 不负责：

- MCP playground UI。
- evaluation harness 主体实现。
- MCP tool contract 主体维护。

### 与开发者 B

需要对齐：

- repo scoped identity。
- repo filter 行为。
- symbol catalog read API。
- incremental indexing 后 stale / deleted item 如何表达。
- provenance 字段如何用于 freshness 判断。

开发者 C 不应提前假设：

- symbol catalog 的表结构。
- code graph 的边结构。
- incremental indexing 的 manifest 格式。

## 验证计划

单元测试：

- tokenization 覆盖中文、英文、camelCase、snake_case、路径、表名、错误码。
- BM25 排序覆盖字段权重。
- alias expansion 覆盖中文业务词到代码符号 / 表名 / 文档标题。
- RRF 测试覆盖 lexical-only、vector-only、symbol-only 候选。
- trace 测试覆盖 channel、rank、score、alias、matched fields。
- context composer 测试覆盖去重、token budget、citation 保留。
- sufficiency 测试覆盖缺 code/schema/doc、低分、缺 provenance、跨 repo 风险。

集成测试：

- `search-code` / `search-db-schema` / `search-doc` 返回结果仍保留 `SearchResult` 基本 contract。
- `build-task-context` 能返回 code、db schema、docs、similar implementations。
- `missing_context` 和 `risks` 能反映缺失或弱证据。
- repo filter 合入后，检索不得跨 repo 污染。

评测验证：

- 对比当前 baseline 和新检索方案的 top-k evidence hit rate。
- 按 code / db_schema / doc 分资产类型观察收益。
- 输出失败样例，指导 alias、字段权重、symbol recall 和 sufficiency 阈值调优。

## 后续优化 / 调优

本次开发完成后，可以单独做调优，但不影响开发者 C 的首轮完整交付。

可调优项：

- BM25 参数。
- 字段权重。
- 中文领域词表。
- alias 词表。
- RRF `k` 值。
- per-channel candidate limit。
- symbol fuzzy 规则。
- token budget 默认值。
- sufficiency / confidence 阈值。
- 是否引入 PostgreSQL Full Text Search。
- 是否持久化 tokens。

## 非目标

- 不实现 GraphRAG。
- 不引入独立搜索服务。
- 不在 Phase 1 直接实现 code graph。
- 不让 MCP 直接访问数据库或 retrieval 内部逻辑。
- 不删除现有 `TaskContext` 字段。
- 不抢开发者 B 的 schema / symbol catalog 设计边界。
