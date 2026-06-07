# MVP 阶段归档

本目录保存已验收 MVP 阶段形成的历史文档。它们用于说明 MVP 阶段的目标、范围、实施路径、验证记录和固定样本，不再作为正式 Pro 开发阶段的当前需求或当前架构入口。

正式文档入口：

- [正式需求](../../product/requirements.md)
- [当前架构设计](../../architecture/design.md)
- [Context API 契约](../../api/context-api.md)
- [MVP 阶段总结](../../planning/mvp-stage-summary.md)
- [正式测评待办](../../evaluation/evaluation-todo.md)

归档内容：

| 文档 | 用途 |
|---|---|
| [MVP 产品需求](product/mvp-requirements.md) | MVP 阶段的问题定义、范围和成功标准 |
| [MVP 架构设计](architecture/mvp-design.md) | MVP 阶段架构、数据流和技术栈说明 |
| [MVP 实施计划](planning/mvp-implementation-plan.md) | MVP 阶段任务拆分、依赖和验收记录 |
| [阶段二实际验证记录](planning/phase-2-verification.md) | 离线索引器端到端落盘验证记录 |
| [阶段三实际验证记录](planning/phase-3-verification.md) | 核心检索流程、接口和真实数据库验证记录 |
| [阶段四实际验证记录](planning/phase-4-verification.md) | MCP 接入、固定评测集和回归脚本验证记录 |
| [阶段五实际验证记录](planning/phase-5-verification.md) | ASGI 入口、配置、embedding、pgvector、索引 CLI 和 remote MCP 验证记录 |
| [MVP 评测计划](evaluation/mvp-evaluation-plan.md) | MVP 阶段固定评测方案 |
| [MVP 固定评测样本](evaluation/mvp-evaluation-samples.json) | MVP 阶段脱敏半真实任务样本 |

`docs/decisions/` 下的 ADR 不移动、不改写。它们是 MVP 阶段形成并继续有效的长期决策记录；如果 Pro 阶段出现新的高影响架构决策，应新增 ADR，而不是重写旧 ADR。
