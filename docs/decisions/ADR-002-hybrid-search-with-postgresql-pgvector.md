# ADR-002: Hybrid Search With PostgreSQL pgvector

## Status

Accepted

## Date

2026-05-12

## Context

代码场景不能只依赖 embedding。

在 Java、SQL 和 Markdown 混合工程资产中，类名、方法名、表名、字段名、annotation、路径和标题层级经常比自然语言相似度更可靠。单纯向量检索可能召回语义相近但工程上无关的结果。

MVP 需要同时验证：

- 关键词命中是否能稳定找到明确符号。
- 向量检索是否能补充语义相近结果。
- 结构化过滤是否能限制资产类型和代码位置。
- 来源引用是否能支撑 Agent 后续判断。

## Decision

MVP 使用 PostgreSQL + pgvector 作为 Index Store。

检索策略采用 `Hybrid Search`：

```text
关键词搜索
+ 向量搜索
+ 结构化过滤
+ 排序与去重
```

PostgreSQL 保存：

- 索引项元数据。
- 来源引用。
- 可检索文本或摘要。
- embedding 向量。
- 结构化过滤字段。

MVP 阶段不引入独立搜索集群、图数据库或 GraphRAG。

## Alternatives Considered

### Milvus

Pros:

- 专用向量数据库。
- 支持较大规模向量检索。

Cons:

- 引入额外部署和运维复杂度。
- MVP 当前规模不需要专用向量集群。
- 结构化元数据和引用模型仍需要额外存储配合。

Rejected because PostgreSQL + pgvector 足够验证 MVP。

### Neo4j

Pros:

- 适合图关系查询。
- 后续可支撑更复杂代码关系。

Cons:

- MVP 不做 GraphRAG 和完整调用链。
- 关系抽取错误会污染结果。
- 会提前把复杂度投入到尚未验证的方向。

Rejected because MVP 应先验证结构化索引和 Hybrid Search。

### OpenSearch

Pros:

- 强关键词搜索能力。
- 支持较成熟的搜索场景。

Cons:

- 增加独立搜索集群运维。
- MVP 仍需要 PostgreSQL 保存结构化数据和引用。
- 当前阶段不需要完整搜索平台能力。

Rejected because MVP 优先降低部署和调试复杂度。

### GraphRAG

Pros:

- 理论上有利于关系推理。
- 适合后续多模块、多层级关系分析。

Cons:

- 关系抽取成本高。
- 错误关系会误导 Agent。
- MVP 的首要问题是可靠召回，不是高级图推理。

Rejected for MVP. GraphRAG can be revisited after fixed evaluation shows basic retrieval is stable.

## Consequences

- 实现需要同时保留关键词、向量和结构化过滤路径。
- 评测失败时，应先排查索引质量、关键词权重和过滤条件，不应直接引入更重架构。
- PostgreSQL schema 需要为后续替换向量库保留边界，不把业务逻辑写死在 pgvector 查询中。
- 所有检索结果必须携带 `SourceCitation`，分数不能替代来源引用。
