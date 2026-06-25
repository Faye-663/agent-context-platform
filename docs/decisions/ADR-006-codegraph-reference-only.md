# ADR-006: CodeGraph 仅作为 Phase 1 参考

## Status

Accepted

## Date

2026-06-24

## Context

ACP 已有 Python、PostgreSQL、repo-scoped citation 和显式增量索引链路。P1-T13 需要判断是否直接接入 `colbymchenry/codegraph`。

调研固定在候选仓库 commit `a7d46073536869dda15a6685b1a188a5fb22bf4d`：该项目采用 MIT 许可，作为独立 CLI/MCP 服务运行，`codegraph init` 创建本地 `.codegraph/` 并通过 watcher 自动维护其图。

## Decision

Phase 1 不直接集成 CodeGraph，不安装其 CLI，不写入 `.codegraph/`，也不将其 MCP server 暴露给 ACP consumer。仅参考其 symbol、call edge、影响分析和调试工作流，为 Phase 2 graph contract 设计提供输入。

## Alternatives Considered

### 直接集成

- 优点：可快速获得调用图和影响分析能力。
- 缺点：引入第二个索引、watcher、MCP runtime 和来源模型，无法保证与 ACP 的 repo/commit/file hash citation 一致。

### 自建 Phase 1 graph runtime

- 优点：完全贴合 ACP 数据模型。
- 缺点：超出 P1-T13 的调研范围，会阻塞当前检索与上下文契约收尾。

## Consequences

- `symbols` 继续只保存 definitions；call edge 与 graph query 留在 Phase 2。
- 未来集成必须先定义 graph node/edge 的 repo、commit、file hash 和增量清理契约，并重新评估 CodeGraph 当前版本。
