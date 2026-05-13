# agent-context-platform

面向 AI Coding Agent 的工程上下文检索系统，用于让 Agent 在方案设计、代码修改、Review 和问题排查时按需获取可信、相关、可引用的工程上下文。

## 当前阶段

项目处于 MVP 阶段一基础能力实现中。当前仓库已包含需求、架构、接口、实施计划、评测方案、关键决策记录，以及阶段一公共模型和存储迁移代码。

已实现范围：

- 公共 Pydantic 模型：`IndexedItem`、`SourceCitation`、`SearchResult`、`TaskContext`。
- SQLAlchemy 存储模型与 `IndexedItemRepository`。
- Alembic 初始迁移，包含 `indexed_items` 表和 PostgreSQL `vector` 扩展。
- 阶段一单元测试，覆盖三类来源引用、JSON 序列化、存储读写和 pgvector 字段声明。

尚未实现范围：

- Java / SQL / Markdown 离线索引器。
- Hybrid Search。
- Context API HTTP 接口。
- `build-task-context` 聚合流程。
- MCP 包装层。
- 固定评测集与回归脚本。

## 文档导航

| 文档 | 用途 |
|---|---|
| [MVP 产品需求](docs/product/mvp-requirements.md) | 说明 MVP 做什么、不做什么、为什么 |
| [MVP 架构设计](docs/architecture/mvp-design.md) | 说明总体架构、数据流和模块边界 |
| [Context API 契约](docs/api/context-api.md) | 说明首版公开接口和统一返回模型 |
| [MVP 实施计划](docs/planning/mvp-implementation-plan.md) | 说明依赖顺序、任务拆分、验收与验证 |
| [MVP 评测计划](docs/evaluation/mvp-evaluation-plan.md) | 说明固定评测集、指标和回归流程 |
| [ADR-001: Agent Context First MVP Scope](docs/decisions/ADR-001-agent-context-first-mvp-scope.md) | 记录 MVP 范围与产品方向决策 |
| [ADR-002: Hybrid Search With PostgreSQL pgvector](docs/decisions/ADR-002-hybrid-search-with-postgresql-pgvector.md) | 记录检索与存储选型决策 |
| [ADR-003: Python FastAPI MVP Application Stack](docs/decisions/ADR-003-python-fastapi-mvp-application-stack.md) | 记录 Python 应用栈、解析器、LLM 和 embedding 边界决策 |

## 核心目标

MVP 的目标不是构建泛知识库，而是构建一个可供 Coding Agent 调用的工程上下文系统。

系统需要支持 Agent：

- 搜索 Java 代码结构和相似实现。
- 搜索 SQL 表结构和字段定义。
- 搜索 Markdown 设计文档和开发规范。
- 聚合任务相关上下文。
- 返回带来源引用的结果。

## MVP 范围

首个验收工作流固定为 `build-task-context`：

```text
用户提出工程任务
    ↓
Agent 调用 build-task-context
    ↓
系统返回相关代码、表结构、设计文档、相似实现和风险提示
    ↓
Agent 基于引用来源继续设计、修改或 Review
```

第一版纳入资产：

- Java 代码：class、method、annotation、signature、file path、line range。
- SQL 表结构：table、column、DDL、index。
- Markdown 文档：heading path、正文片段、file path、line range。

## 明确不做

MVP 阶段不做：

- 人工搜索 UI。
- 泛知识库问答。
- PPT、PDF、图片或流程图解析。
- GraphRAG。
- 实时索引。
- 权限系统。
- 多仓库关联。

这些能力可以在 MVP 的核心检索质量被验证后再评估。

## 验收口径

MVP 必须通过固定评测集验证，不以单次演示效果作为完成标准。

基础指标：

- Top5 命中率 >= 70%。
- Top10 明显无关结果 <= 3 条。
- 所有返回结果必须包含来源引用。

详细方案见 [MVP 评测计划](docs/evaluation/mvp-evaluation-plan.md)。

## 本地验证

阶段一单元测试：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test pytest
```

PostgreSQL 迁移使用 `ACP_DATABASE_URL` 指定数据库连接：

```powershell
$env:ACP_DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/agent_context_platform"
uv run alembic upgrade head
```

当前开发机已验证过一套隔离 PostgreSQL / pgvector 环境：

```powershell
$toolRoot = "D:\Code\ACPTools"
$env:PIXI_HOME = Join-Path $toolRoot "pixi-home"
$env:PIXI_CACHE_DIR = Join-Path $toolRoot "pixi-cache"
$env:ACP_DATABASE_URL = "postgresql+psycopg://postgres@localhost:55432/agent_context_platform"

& "$toolRoot\pixi.exe" run --manifest-path "$toolRoot\pg-pixi\pixi.toml" pg_ctl -D "$toolRoot\pg-data" -l "$toolRoot\postgres.log" -o "-p 55432" start
uv run alembic upgrade head
```

本阶段没有硬编码 embedding 维度，因为具体 EmbeddingProvider、模型名和向量维度仍在实施计划的待确认问题中。
