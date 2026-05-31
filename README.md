# agent-context-platform

面向 AI Coding Agent 的工程上下文检索系统，用于让 Agent 在方案设计、代码修改、Review 和问题排查时按需获取可信、相关、可引用的工程上下文。

## 当前阶段

项目处于 MVP 阶段五收口中。当前仓库已包含需求、架构、接口、实施计划、评测方案、关键决策记录，以及阶段一公共模型、阶段二离线索引器、阶段三检索 / Context API / 任务上下文构建代码、阶段四 MCP 包装层 / 固定评测回归脚本和阶段五固定 ASGI 入口 / 运行配置加载能力、DashScope 与 OpenAI-compatible embedding provider、批量 embedding 写入能力、数据库侧 pgvector 相似度排序与真实项目初始化索引 CLI。

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
- 固定 ASGI 入口与运行配置加载：提供 `agent_context_platform.asgi:app`、`ACP_DATABASE_URL` 运行配置和 embedding provider 配置校验。
- EmbeddingProvider：通过 `ACP_EMBEDDING_*` 配置生成 query embedding 和 item embedding，当前支持 DashScope native、OpenAI-compatible 和 Jina task mode。
- 多模型 embedding 存储：`item_embeddings` 按 `provider`、`model`、`dimension` 保存 embedding，避免把当前模型维度固定进 `indexed_items` 主表。
- 批量 embedding 写入：支持把 Java、SQL、Markdown 三类离线索引结果生成 embedding 后落库。
- 数据库侧 pgvector 相似度排序：provider/model/dimension 明确时，repository 层使用 PostgreSQL / pgvector 的 `<=>` 完成 query embedding 相似度排序，并保留关键词候选的有界合并。
- 初始化索引 CLI：提供 `acp-index --root <path>`，支持 `dry-run`、include/exclude、显式 repo 标识、复用 `ACP_DATABASE_URL` 写库和显式 `--with-embedding` 写入 embedding。

尚不满足真实可用 MVP 的项：

- 基于真实脱敏 Java 项目索引库的召回评测。
- 真实 MySQL dump 风格 SQL 的索引兼容性。jshERP 的 `jsh_erp.sql` 已暴露当前 SQL indexer 对 MySQL `SET NAMES`、反引号标识符、`AUTO_INCREMENT`、`COMMENT` 等语法不兼容，需要在任务 15 前作为真实项目修复项处理。
- Jina/OpenAI-compatible provider 的真实外部调用验证。当前已有单元测试覆盖请求体、响应解析、错误处理和 Jina `retrieval.passage` / `retrieval.query` task 分流；正式验收前还需要用真实 API key 做端到端写入与检索验证。

阶段五当前已经补齐固定 ASGI 入口、外部 embedding provider、批量 embedding 写入、数据库侧 pgvector 排序和通用初始化索引 CLI；这仍不等同于真实项目 MVP 验收完成。真实可用 MVP 还需要用真实脱敏 Java 项目索引库验证召回质量。

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
| [阶段五实际验证记录](docs/planning/phase-5-verification.md) | 记录 ASGI 入口、运行配置、embedding provider、批量写入、pgvector 排序和初始化索引 CLI 验证结果 |
| [MVP 评测计划](docs/evaluation/mvp-evaluation-plan.md) | 说明固定评测集、指标和回归流程 |
| [MVP 固定评测样本](docs/evaluation/mvp-evaluation-samples.json) | 保存阶段四脱敏半真实任务样本 |
| [ADR-001: Agent Context First MVP Scope](docs/decisions/ADR-001-agent-context-first-mvp-scope.md) | 记录 MVP 范围与产品方向决策 |
| [ADR-002: Hybrid Search With PostgreSQL pgvector](docs/decisions/ADR-002-hybrid-search-with-postgresql-pgvector.md) | 记录检索与存储选型决策 |
| [ADR-003: Python FastAPI MVP Application Stack](docs/decisions/ADR-003-python-fastapi-mvp-application-stack.md) | 记录 Python 应用栈、解析器、LLM 和 embedding 边界决策 |
| [ADR-004: Model Scoped Embedding Storage](docs/decisions/ADR-004-model-scoped-embedding-storage.md) | 记录多 embedding model 兼容存储决策 |

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

## 运行依赖

- Python `>= 3.12`
- [`uv`](https://docs.astral.sh/uv/)：用于安装依赖和执行项目命令
- PostgreSQL：用于真实数据库验证
- `pgvector` extension：用于 `item_embeddings.embedding` 字段和后续向量检索能力

当前文档默认使用 Windows / PowerShell。`pyproject.toml` 已声明项目依赖，`uv.lock` 固定了当前锁定版本。

## 配置说明

仓库提供 [`.env.example`](.env.example) 作为配置样例。应用本身只读取进程环境，不会自动加载 `.env` 文件；本地启动时可以让 Uvicorn 通过 `--env-file .env` 把样例文件加载到进程环境中。

注意：Alembic 和 `acp-index` 当前不会自动读取 `.env` 文件，只读取当前 PowerShell 进程环境变量。执行迁移或索引前，需要先把 `.env` 加载到当前进程，或者直接设置对应 `$env:*` 变量；`uvicorn --env-file .env` 只对 Uvicorn 启动生效，不会影响 Alembic 或 `acp-index`。

| 变量 | 用途 | 默认行为 |
|---|---|---|
| `ACP_DATABASE_URL` | 指定 Alembic 迁移、初始化索引 CLI 和长期运行 Context API 使用的数据库连接 | 固定 ASGI 入口和 `acp-index` 写库时必填 |
| `ACP_ENV` | 标识运行环境 | 默认 `local` |
| `ACP_LOG_LEVEL` | 指定应用日志级别 | 默认 `INFO` |
| `ACP_SQL_ECHO` | 控制 SQLAlchemy 是否输出 SQL 日志 | 默认 `false` |
| `ACP_CONTEXT_API_BASE_URL` | 指定 MCP server 调用的 Context API 地址 | 默认 `http://127.0.0.1:8000` |
| `ACP_EMBEDDING_PROVIDER` | 选择 embedding provider | 可选 `dashscope`、`openai`、`jina`；不填时默认 `dashscope` |
| `ACP_EMBEDDING_BASE_URL` / `ACP_EMBEDDING_API_KEY` / `ACP_EMBEDDING_MODEL` / `ACP_EMBEDDING_DIMENSION` / `ACP_EMBEDDING_BATCH_SIZE` | embedding provider 基础配置组 | 如果填写其中任意一项，则必须整组填写，`ACP_EMBEDDING_BATCH_SIZE` 必须为正整数；`acp-index` 只有传入 `--with-embedding` 时才会调用 provider |
| `ACP_EMBEDDING_DOCUMENT_TASK` / `ACP_EMBEDDING_QUERY_TASK` | Jina / OpenAI-compatible task mode | 可选；`provider=jina` 默认使用 `retrieval.passage` 写入 item embedding、`retrieval.query` 生成 query embedding |

## 快速开始

以下命令默认在 Windows / PowerShell 中执行。

1. 复制配置样例：

   ```powershell
   Copy-Item .env.example .env
   ```

2. 编辑 `.env`，至少确认 `ACP_DATABASE_URL` 指向可用 PostgreSQL / pgvector 数据库。需要写入 embedding 时，还必须确认 `ACP_EMBEDDING_PROVIDER`、`ACP_EMBEDDING_API_KEY`、`ACP_EMBEDDING_MODEL` 和维度配置匹配当前 provider。

3. 在当前 PowerShell 进程中设置本仓库本地依赖缓存：

   ```powershell
   $env:UV_CACHE_DIR = ".uv-cache"
   $env:UV_PYTHON_INSTALL_DIR = ".uv-python"
   ```

4. 安装项目依赖：

   ```powershell
   uv sync --extra test
   ```

5. 将 `.env` 中的运行配置加载到当前进程，并执行数据库迁移：

   ```powershell
   Get-Content .env | ForEach-Object {
       if ($_ -and -not $_.TrimStart().StartsWith("#") -and $_.Contains("=")) {
           $name, $value = $_.Split("=", 2)
           Set-Item -Path "Env:$($name.Trim())" -Value $value.Trim().Trim('"')
       }
   }
   uv run alembic upgrade head
   ```

6. 运行完整测试：

   ```powershell
   uv run --extra test pytest
   ```

7. 初始化工程索引。先用 `dry-run` 确认扫描边界，再写入与 Context API 相同的 `ACP_DATABASE_URL`：

   ```powershell
   uv run acp-index --root D:\Code\YourProject --dry-run
   uv run acp-index --root D:\Code\YourProject --repo your-project
   ```

   如果开启新的 PowerShell 终端，需要重新加载 `.env` 或重新设置 `$env:ACP_DATABASE_URL`，否则 `acp-index` 读取不到数据库连接。

   如需同时写入 embedding，必须先补齐 `ACP_EMBEDDING_*`，并显式传入 `--with-embedding`：

   ```powershell
   uv run acp-index --root D:\Code\YourProject --repo your-project --with-embedding
   ```

8. 启动长期运行的 Context API：

   ```powershell
   uv run uvicorn agent_context_platform.asgi:app --host 127.0.0.1 --port 8000 --env-file .env
   ```

9. 另开一个 PowerShell 终端，启动 MCP server wrapper：

   ```powershell
   $env:ACP_CONTEXT_API_BASE_URL = "http://127.0.0.1:8000"
   uv run acp-mcp-server
   ```

## 当前启动边界

固定 ASGI 入口位于 `agent_context_platform.asgi:app`，可通过 Uvicorn 启动长期运行的 Context API。运行时配置由 `agent_context_platform.runtime` 统一加载；缺少 `ACP_DATABASE_URL`、日志级别格式错误或 embedding provider 配置不完整时，会在启动阶段直接失败，而不是把问题留到请求阶段。

MCP server 仍然只是 Context API 的包装层；它依赖可访问的 HTTP 服务，但不直接访问 repository、SQLAlchemy session 或数据库。当前已完成外部 EmbeddingProvider 调用、批量 embedding 写入和数据库侧 pgvector 相似度排序。

真实项目入库入口是离线批处理命令 `acp-index`，不是 Context API 或 MCP server 的一部分。第一版 P0 支持扫描单个工程目录、复用 `ACP_DATABASE_URL`、`dry-run`、include/exclude、稳定 repo 标识和 JSON 结果摘要；embedding 写入必须显式传入 `--with-embedding`。

当前任务 15 真实项目验证已暴露后续修复项：jshERP 的 MySQL dump SQL 文件无法被现有 PostgreSQL 方言 SQL indexer 完整解析。面向 MySQL 项目验收前，需要补齐 MySQL DDL 方言支持或 dump 预处理，并用代表性 MySQL DDL 样本增加回归测试。另一个后续项是 Jina/OpenAI-compatible provider 的真实外部验证：当前代码已实现 provider 选择和请求/响应解析，但切换 provider、model、dimension 或 Jina task pair 后仍必须重新生成对应 `item_embeddings`，不能混用不同向量空间。

## 本地验证

### 基础验证

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test pytest
```

当前任务 14 后验证结果：

- `uv run --extra test pytest`：`63 passed`

### 固定评测集回归

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test python scripts/run_mvp_evaluation.py
```

当前结果：

- `sample_count=10`
- `passed=true`
- `top5_hit_rate=1.0`
- `top10_irrelevant_result_count=0`
- `source_citation_completeness=1.0`

### 固定 ASGI 入口验证

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run uvicorn agent_context_platform.asgi:app --host 127.0.0.1 --port 8000 --env-file .env
```

服务启动后，可以用任意 HTTP client 调用 `/search-code`、`/search-db-schema`、`/search-doc` 和 `/build-task-context`。固定 ASGI 入口的真实 PostgreSQL / pgvector 冒烟验证记录见 [阶段五实际验证记录](docs/planning/phase-5-verification.md)。

### MCP 包装层验证

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test pytest tests/test_mcp_server.py
```

当前结果：

- `uv run --extra test pytest tests/test_mcp_server.py`：`4 passed`

### 本地 PostgreSQL / pgvector 启动

当前开发机已验证过一套隔离 PostgreSQL / pgvector 环境，工具链位于 `D:\Code\ACPTools`。如果使用这套本地环境：

```powershell
$toolRoot = "D:\Code\ACPTools"
$env:PIXI_HOME = Join-Path $toolRoot "pixi-home"
$env:PIXI_CACHE_DIR = Join-Path $toolRoot "pixi-cache"
$env:ACP_DATABASE_URL = "postgresql+psycopg://postgres@localhost:55432/agent_context_platform"

& "$toolRoot\pixi.exe" run --manifest-path "$toolRoot\pg-pixi\pixi.toml" pg_ctl -D "$toolRoot\pg-data" -l "$toolRoot\postgres.log" -o "-p 55432" start
uv run alembic upgrade head
```

验证完成后停止本地数据库：

```powershell
& "$toolRoot\pg-pixi\.pixi\envs\default\Library\bin\pg_ctl.exe" -D "$toolRoot\pg-data" stop
```

### 任务 12 embedding 写入验证

`.env` 必须包含完整 `ACP_EMBEDDING_*` 配置。该验证会真实调用当前配置的 embedding provider，并将 Java、SQL、Markdown 三类样本 embedding 写入数据库。当前已执行过 DashScope provider 真实调用；Jina/OpenAI-compatible provider 仍需要单独补真实外部调用验证：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test python scripts/verify_task12_embeddings.py --env-file .env
```

当前已验证输出摘要：

- `saved_count=3`
- `embedding_counts=code:1,db_schema:1,doc:1`
- query embedding 检索返回非零 vector score

### 任务 14 初始化索引 CLI 验证

`acp-index` 会输出 JSON 摘要，包含 `repo`、`database`、`files_scanned`、`files_indexed`、`items_estimated`、`items_written`、`items_failed`、`embedding_written`、`elapsed_seconds` 和 `failures`。

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run acp-index --root . --dry-run
```

写库时必须设置 `ACP_DATABASE_URL`，该数据库应与 Context API 启动时读取的数据库一致：

```powershell
$env:ACP_DATABASE_URL = "postgresql+psycopg://postgres@localhost:55432/agent_context_platform"
uv run alembic upgrade head
uv run acp-index --root D:\Code\YourProject --repo your-project
```

常用过滤参数：

```powershell
uv run acp-index --root D:\Code\YourProject --include "**/*.java" --exclude "target/**" --dry-run
```

### 任务 13 pgvector 排序验证

该验证不依赖外部 embedding provider。脚本会写入确定性样本，调用 repository 的 PostgreSQL / pgvector 查询，并断言 SQL 实际使用 `<=>` 和 `LIMIT`：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
$env:ACP_DATABASE_URL = "postgresql+psycopg://postgres@localhost:55432/agent_context_platform_task13"
uv run alembic upgrade head
uv run --extra test python scripts/verify_task13_pgvector_search.py
```

当前已验证输出：

- `task13 pgvector search verification passed`
- `top_result=task13:code:vector-top`
- `vector_score=1.0`
- `operator=<=>`
- `limit_applied=true`
