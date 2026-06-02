# Post-MVP 待办

## 说明

本文记录已经发现、但不作为当前 MVP 验收范围的工程问题。

纳入本文的事项应满足：

- 当前实现可以支撑单仓或单项目 MVP 验证。
- 问题会影响后续产品化、多项目使用或长期维护。
- 现在直接修复会扩大 MVP 范围，或需要先确认更清晰的使用场景。

## 待办项

### P1: 多仓共库检索隔离

**状态：** Backlog

**是否属于 MVP：** 否。当前 MVP 重点验证单个真实项目的离线索引、embedding 写入、检索与 `build-task-context` 工作流。多仓共用同一索引库属于后续产品化能力。

**当前实现：**

- `acp-index --repo` 会把 repo 标识写入 `SourceCitation.repo`。
- `SourceCitation.repo` 会落库到 `indexed_items.repo`，并随检索结果返回。
- keyword 检索当前按 `title`、`content`、`summary`、`symbol`、`table_name`、`heading_path`、`path` 做匹配，不把 `repo` 作为匹配字段或过滤条件。
- vector 检索通过 `item_embeddings.item_id` join `indexed_items`，但当前过滤条件只有 `asset_type`、`path_prefix`、`language`、`symbol_types`、`table`，没有 `repo`。
- 当前 `IndexedItem.id` 不包含 repo，例如 `code:{path}:{symbol}`、`db_schema:{path}:{table}`、`doc:{path}:{heading_path}`。

**风险：**

- 多个 repo 写入同一数据库时，keyword 和 vector 检索都可能跨 repo 召回。
- 如果两个 repo 存在相同相对路径和相同 symbol/table/heading，`indexed_items.id` 可能冲突；当前 `save()` 使用 merge 写入，存在覆盖旧 item 的风险。

**后续成功标准：**

- 调用方可以按 repo 限定 keyword 和 vector 候选集。
- 多 repo 写入同一数据库时，不会因为相同相对路径和 symbol/table/heading 覆盖彼此。
- `SearchResult.source.repo` 继续作为结果来源返回。
- 相关 repository、retrieval、API/MCP filter 和 CLI 行为有单元测试或集成测试覆盖。

**待确认问题：**

- 是否要支持一个数据库保存多个 repo，还是每个 repo 使用独立数据库。
- 如果支持多 repo 共库，`repo` 应作为过滤条件、主键组成部分，还是引入独立 project/workspace 概念。
- 旧数据迁移时，现有不含 repo 的 `item.id` 是否需要重建。
