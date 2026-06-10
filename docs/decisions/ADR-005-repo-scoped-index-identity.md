# ADR-005: Repo Scoped Index Identity

## Status

Accepted

## Date

2026-06-10

## Context

ACP 需要支持多个 GitLab code repo 写入同一个索引数据库。当前 `IndexedItem.id` 只由 asset type、相对路径和 symbol/table/heading 组成；不同 repo 中如果存在相同相对路径和 symbol，`session.merge` 会把后写入的 item 覆盖先写入的 item。

仅把 `repo` 作为返回字段或查询过滤条件不能解决覆盖问题。`repo` 必须进入持久化 identity，才能保证多 code repo 共库时同名 item 可以并存。

## Decision

`repo` 使用规范化 GitLab code repo identity，例如 `gitlab.example.com/group/project`。生产索引必须通过 `acp-index --repo` 显式传入该值；本地根目录名只保留为调试 fallback。

`indexed_items` 使用 `(repo, id)` 作为存储主键。`item_embeddings` 使用 `(repo, item_id, provider, model, dimension)` 作为主键，并通过 `(repo, item_id)` 复合外键关联 `indexed_items`。

Context API 支持 `filters.repo` 和 `build-task-context.constraints.repo`。单 repo 本地运行可设置 `ACP_DEFAULT_REPO` 自动注入 repo；`ACP_REQUIRE_REPO_FILTER=true` 时，请求和默认配置都缺少 repo 会返回 `invalid_request`。

旧索引数据是可重建派生数据，不尝试猜测归属；升级后需要重新执行 `acp-index`。

## Alternatives Considered

### Prefix repo into `IndexedItem.id`

- Pros:
  - 数据库主键改动较少。
  - 单列外键和旧查询路径更简单。
- Cons:
  - 公开 `item.id` 会变成跨 repo 拼接格式。
  - evaluation 样本、trace 和后续 symbol identity 会把 repo 编码细节当成 item id 语义。
- Why not chosen:
  - `repo` 是隔离维度，不应泄漏进 item 局部身份。

### Repo as query filter only

- Pros:
  - 改动最小。
  - API 层可快速避免部分误召回。
- Cons:
  - 写入时仍会覆盖同 id item。
  - embedding 仍可能跨 repo 错连。
- Why not chosen:
  - 无法解决 `P1-T5` 的核心覆盖问题。

### One database per repo

- Pros:
  - 天然隔离。
  - schema 改动少。
- Cons:
  - 无法支持共享服务下的多 repo 检索基础。
  - 后续跨 repo 关系、评测和运维需要管理多个数据库。
- Why not chosen:
  - `P1-T5` 的目标是同一数据库内的 multi code repo 隔离。

## Consequences

- 所有持久化写入必须携带 `source.repo`。
- retrieval、trace、RRF 和 symbol recall 后续必须把候选身份视为 `(repo, id)`，不能只按 `id` 去重。
- 迁移不保留旧索引数据；维护者需要重新运行 `acp-index`。
- `repo` 不表达 doc/code/sql 与 organization 的业务关系；这些关系需要独立模型。
