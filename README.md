# agent-context-platform

面向 AI Coding Agent 的工程上下文检索系统，用于让 Agent 在方案设计、代码修改、Review 和问题排查时按需获取可信、相关、可引用的工程上下文。

## 当前阶段

项目处于 MVP 阶段四已完成、后续需要进入真实可用 MVP 收口状态。当前仓库已包含需求、架构、接口、实施计划、评测方案、关键决策记录，以及阶段一公共模型、阶段二离线索引器、阶段三检索 / Context API / 任务上下文构建代码和阶段四 MCP 包装层 / 固定评测回归脚本。

已实现范围：

- 公共 Pydantic 模型：`IndexedItem`、`SourceCitation`、`SearchResult`、`TaskContext`。
- SQLAlchemy 存储模型与 `IndexedItemRepository`。
- Alembic 初始迁移，包含 `indexed_items` 表和 PostgreSQL `vector` 扩展。
- 阶段一单元测试，覆盖三类来源引用、JSON 序列化、存储读写和 pgvector 字段声明。
- Java 离线索引器：基于 `tree-sitter-java` 抽取 class、method、annotation、signature、file path 和 line range。
- SQL DDL 离线索引器：基于 `sqlglot` 抽取 table、column、index 和 DDL 来源。
- Markdown 离线索引器：基于 `markdown-it-py` 抽取 heading path、正文片段、file path 和 line range。
- 阶段二单元测试与实际落盘验证，覆盖三类样本索引、来源引用和 repository 写读链路。
- 混合检索：支持关键词分数、embedding 余弦相似度、结构化过滤和统一 `SearchResult`。
- Context API：提供 `search-code`、`search-db-schema`、`search-doc` 三类检索接口。
- `build-task-context`：聚合代码、表结构、文档和相似实现，并在上下文不足时返回 `missing_context` 与 `risks`。
- 阶段三测试与运行时验证脚本，覆盖接口响应、日志、错误路径和真实数据库写读检索链路。
- MCP 包装层：基于 MCP Python SDK `FastMCP` 暴露 `search-code`、`search-db-schema`、`search-doc` 和 `build-task-context` 对应工具，包装层只调用 Context API。
- 固定评测集与回归脚本：包含 10 个脱敏半真实工程任务样本，可计算 Top5 命中率、Top10 明显无关结果数量和来源引用完整率。

尚不满足真实可用 MVP 的项：

- 面向部署的固定 ASGI 入口和运行配置加载器。
- 外部 EmbeddingProvider 调用与批量 embedding 写入流程。
- 数据库侧 pgvector 相似度排序。
- 基于真实脱敏 Java 项目索引库的召回评测。

阶段四通过的是固定脱敏样本回归，说明 MVP 骨架、Context API、MCP 包装层和评测脚本已经跑通；这不等同于真实项目 MVP 验收完成。真实可用 MVP 还需要完成上述收口项，并用真实脱敏 Java 项目索引库验证召回质量。

## 文档导航

| 文档 | 用途 |
|---|---|
| [MVP 产品需求](docs/product/mvp-requirements.md) | 说明 MVP 做什么、不做什么、为什么 |
| [MVP 架构设计](docs/architecture/mvp-design.md) | 说明总体架构、数据流和模块边界 |
| [Context API 契约](docs/api/context-api.md) | 说明首版公开接口和统一返回模型 |
| [MVP 实施计划](docs/planning/mvp-implementation-plan.md) | 说明依赖顺序、任务拆分、验收与验证 |
| [阶段二实际验证记录](docs/planning/phase-2-verification.md) | 记录离线索引器端到端落盘验证结果和未覆盖边界 |
| [阶段三实际验证记录](docs/planning/phase-3-verification.md) | 记录核心检索流程、接口和真实数据库验证结果 |
| [阶段四实际验证记录](docs/planning/phase-4-verification.md) | 记录 MCP 接入、固定评测集和回归脚本验证结果 |
| [MVP 评测计划](docs/evaluation/mvp-evaluation-plan.md) | 说明固定评测集、指标和回归流程 |
| [MVP 固定评测样本](docs/evaluation/mvp-evaluation-samples.json) | 保存阶段四脱敏半真实任务样本 |
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

单元测试：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test pytest
```

当前阶段三验证结果：

- `uv run --extra test pytest`：`20 passed`
- `uv run --extra test python scripts/verify_phase3_runtime.py`：通过 FastAPI app factory 实际调用 `search-code`、`search-db-schema`、`search-doc` 和 `build-task-context`。
- 真实 PostgreSQL / pgvector 验证：在 `ACP_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/agent_context_platform` 下执行迁移与运行时验证通过。
- 验证记录见 [阶段三实际验证记录](docs/planning/phase-3-verification.md)。

当前通过 `create_app(search_service)` 创建 FastAPI app，用于测试、脚本验证和 MCP 包装层背后的 Context API 服务。仓库暂未提供固定的 `agent_context_platform.api:app` 部署入口；如果需要启动长期运行的 HTTP 服务，应先补运行配置和应用装配层。

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

阶段三已覆盖真实 PostgreSQL + pgvector 写读和运行时检索路径。当前混合检索在应用侧计算关键词分数和向量余弦相似度；仍未实现外部 EmbeddingProvider 调用和数据库侧 pgvector 相似度排序，验证脚本使用固定测试向量写入 `embedding` 字段。

MCP 包装层验证：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test pytest tests/test_mcp_server.py
```

固定评测集回归：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test python scripts/run_mvp_evaluation.py
```

当前阶段四验证结果：

- `uv run --extra test pytest tests/test_mcp_server.py`：`4 passed`
- `uv run --extra test pytest tests/test_evaluation.py`：`2 passed`
- `uv run --extra test pytest`：`26 passed`
- `uv run --extra test python scripts/run_mvp_evaluation.py`：`sample_count=10`，`passed=true`，`top5_hit_rate=1.0`，`top10_irrelevant_result_count=0`，`source_citation_completeness=1.0`

MCP server 默认通过 `acp-mcp-server` 启动，并调用 `http://127.0.0.1:8000` 上的 Context API；可以用 `ACP_CONTEXT_API_BASE_URL` 覆盖目标地址。由于仓库尚未提供固定 ASGI 部署入口，长期运行 HTTP 服务前仍需先补应用装配层。
