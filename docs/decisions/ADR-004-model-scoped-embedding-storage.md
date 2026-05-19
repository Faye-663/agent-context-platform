# ADR-004: Model Scoped Embedding Storage

## Status

Accepted

## Date

2026-05-19

## Context

任务 12 接入外部 EmbeddingProvider 后，系统需要支持不同 embedding model。不同模型可能返回不同维度，甚至同一 provider 后续也可能更换模型或输出维度。

如果直接把 `indexed_items.embedding` 固定成 `vector(768)`，当前 DashScope 模型可以工作，但后续切换模型会要求数据库迁移或重建列定义。这会把 embedding model 的短期选择泄漏成长期 schema 承诺。

## Decision

新增 `item_embeddings` 表，按 `item_id`、`provider`、`model`、`dimension` 存储 embedding。

`indexed_items` 继续只保存工程资产与来源引用。embedding 属于可重建派生数据，按模型身份独立保存。

PostgreSQL 中 `embedding` 列保持 pgvector 无固定维度 `vector`。数据库层使用动态约束 `vector_dims(embedding) = dimension`，应用层在写入和查询前也校验当前 provider/model/dimension，避免不同维度互相比较。

## Alternatives Considered

### Fixed `vector(768)` column

- Pros:
  - schema 简单。
  - 当前已验证 DashScope 模型正好返回 768 维。
- Cons:
  - 不能兼容不同 embedding model。
  - 切换模型时需要迁移列或重建索引。
  - 会把当前模型维度变成对外长期约束。
- Why not chosen:
  - 用户明确要求兼容不同 embedding model。

### Keep embedding on `indexed_items`

- Pros:
  - 改动最小。
  - 现有 repository 写入路径更简单。
- Cons:
  - 每个 item 只能自然表达一个 embedding。
  - 多模型共存时需要覆盖旧向量或增加不清晰的列。
- Why not chosen:
  - embedding 是模型相关派生数据，应该从资产主表拆出。

## Consequences

- 查询侧必须明确使用当前 provider/model/dimension 对应的 item embedding。
- 任务 13 做数据库侧 pgvector 排序时，需要按 provider/model/dimension 建立查询和索引边界。
- 历史无模型身份的 embedding 在迁移中作为 `legacy/legacy/<dimension>` 保留。
