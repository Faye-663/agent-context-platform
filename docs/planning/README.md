# Planning 文档导航

## 当前入口

| 文档 | 用途 |
|---|---|
| [Phase 1 当前状态汇总](phase1-current-status.md) | 汇总三人协作后的当前完成度、已合入能力、待完善项和下一步 |
| [Phase 1 三人并行开发分工](phase1-parallel-development-plan.md) | 记录 A/B/C 的职责边界和协作接口 |
| [后续待办与阶段规划](post-mvp-todo.md) | 记录尚未转为正式需求的 Phase 1 / Phase 2 待办 |
| [MVP 阶段总结](mvp-stage-summary.md) | 阶段 0 归档入口和验收结论 |

## 个人与开发流文档

以下文档保留为实现过程、方案讨论和证据材料，不再作为当前状态唯一入口：

| 目录 | 说明 |
|---|---|
| `developer-a/` | 开发者 A 的 evaluation、MCP contract、Playground 方案和进展 |
| `jhchen258/` | 开发者 C 的 retrieval、alias、RRF、context composer 方案和进展 |

开发者 B 的进度主要通过已合入 PR、`post-mvp-todo.md` 中的状态同步，以及架构 / 产品文档体现。

## 精简原则

- 当前状态统一看 `phase1-current-status.md`，避免分别翻个人方案判断完成度。
- 个人方案文档不删除，作为细节证据和后续 review 背景保留。
- 阶段状态材料统一放到 `docs/reports/`，不混入长期规划文档。
