# agent-context-platform

面向 AI Coding Agent 的工程上下文检索系统，用于让 Agent 在方案设计、代码修改、Review 和问题排查时按需获取可信、相关、可引用的工程上下文。

## 当前阶段

agent-context-platform 按生产级项目维护当前文档和运行边界。当前进展是阶段 0：MVP 开发与验收已完成；Phase 1 基础能力已基本合入 `master`，正在进入真实数据验证和效果调优阶段。

当前正式文档不把后续生产化计划写成既定路线图。正式生产化优先级、部署形态和权限边界仍待后续确认。

当前已实现能力：

- 公共 Pydantic 模型：`IndexedItem`、`SourceCitation`、`SearchResult`、`TaskContext`、`SymbolCatalogEntry`。
- Java、SQL DDL、Markdown 离线索引器。
- SQLAlchemy repository、Alembic 迁移、PostgreSQL / pgvector 存储。
- 索引来源 provenance：`acp-index` 写入 repo、best-effort branch / commit、file hash、index time 和 index batch。
- Multi code repo 共库隔离：`repo + id` 作为存储身份，检索支持 repo filter。
- Symbol catalog：`symbols` 按 repo 隔离保存 Java / SQL symbol definitions，供后续 symbol recall 和 code graph 消费。
- Hybrid Search：lexical、vector、symbol 多路召回，RRF 融合和统一 `SearchResult`。
- 中文 lexical retrieval：`jieba` search mode、工程词典、alias expansion 和无分词器 fallback。
- Context Composer：token budget、`missing_context`、待确认项和 citation 汇总。
- Context API：`/search-code`、`/search-db-schema`、`/search-doc`、`/build-task-context`。
- DebugOptions：search / build-task-context 支持 `debug_options.include_trace`。
- MCP wrapper：`search_code`、`search_db_schema`、`search_doc`、`build_task_context`。
- Evaluation：`eval/golden-tasks.json`、`acp-eval` CLI 和回归测试入口。
- MCP Web Playground：`playground/` 提供开发调试入口。
- 固定 ASGI 入口：`agent_context_platform.asgi:app`。
- 初始化索引 CLI：`acp-index --root <path>`。
- Embedding provider：OpenAI-compatible `/v1/embeddings` 和 message-style `/infer`。
- 多模型 embedding 存储：`item_embeddings` 按 provider、model 和 dimension 隔离向量空间。
- Remote MCP HTTP：`ACP_MCP_TRANSPORT=streamable-http`。
- MCP JSONL 调试日志：默认关闭，可显式写摘要或完整 payload。

## 文档导航

### 正式文档

| 文档 | 用途 |
|---|---|
| [正式需求](docs/product/requirements.md) | 当前产品和工程需求入口 |
| [当前架构设计](docs/architecture/design.md) | 当前 master 代码对应的架构、入口、配置和边界 |
| [Context API 契约](docs/api/context-api.md) | HTTP API、MCP 参数透传、模型和错误 envelope |
| [正式测评待办](docs/evaluation/evaluation-todo.md) | 正式测评体系待确认事项 |
| [Phase 1 当前状态汇总](docs/planning/phase1-current-status.md) | 三人协作后的当前完成度、待完善项和下一步 |
| [2026-06-17 Phase 1 状态材料](docs/reports/2026-06-17-phase1-review/README.md) | 阶段成果、验证流程、三人交付对照和后续计划 |
| [ADR-001](docs/decisions/ADR-001-agent-context-first-mvp-scope.md) | Agent Context First MVP 范围决策 |
| [ADR-002](docs/decisions/ADR-002-hybrid-search-with-postgresql-pgvector.md) | Hybrid Search 与 PostgreSQL / pgvector 决策 |
| [ADR-003](docs/decisions/ADR-003-python-fastapi-mvp-application-stack.md) | Python FastAPI 应用栈决策 |
| [ADR-004](docs/decisions/ADR-004-model-scoped-embedding-storage.md) | 多模型 embedding 存储决策 |
| [ADR-005](docs/decisions/ADR-005-repo-scoped-index-identity.md) | Multi code repo 共库隔离身份决策 |

### 阶段记录与历史资料

| 文档 | 用途 |
|---|---|
| [MVP 阶段总结](docs/planning/mvp-stage-summary.md) | 阶段 0 已完成能力、验收结论和转入生产化阶段的边界 |
| [MVP 阶段归档](docs/archive/mvp/README.md) | 阶段 0 历史需求、设计、计划、验证和样本 |

ADR 保持历史原貌，不因进入生产化阶段改写。后续如果出现新的高影响架构决策，应新增 ADR。

## 核心工作流

默认 Agent 工作流是 `build-task-context`：

```text
用户提出工程任务
    ↓
Agent 调用 build-task-context
    ↓
系统返回相关代码、表结构、文档、相似实现和待确认项
    ↓
Agent 基于 source citation 继续设计、修改或 Review
```

每条返回结果都必须有可追溯来源。`acp-index` 写入的结果会携带 repo、文件 hash、索引时间和索引批次；Git branch / commit 以 best-effort 方式采集，非 Git 目录允许为空。上下文不足时，系统应通过 `missing_context` 等结构化字段暴露缺口，而不是伪造确定结论。

## 运行依赖

- Python `>= 3.12`
- [`uv`](https://docs.astral.sh/uv/)
- PostgreSQL
- `pgvector` extension

当前文档默认使用 Windows / PowerShell。`pyproject.toml` 声明项目依赖和脚本入口，`uv.lock` 固定当前锁定版本。

## 配置说明

仓库提供 [`.env.example`](.env.example) 作为配置样例。应用本身只读取进程环境，不会自动加载 `.env` 文件；本地启动时可以让 Uvicorn 通过 `--env-file .env` 把样例文件加载到 Uvicorn 进程环境中。

注意：Alembic 和 `acp-index` 当前不会自动读取 `.env` 文件，只读取当前 PowerShell 进程环境变量。执行迁移或索引前，需要先把 `.env` 加载到当前进程，或者直接设置对应 `$env:*` 变量；`uvicorn --env-file .env` 不会影响 Alembic 或 `acp-index`。

| 变量 | 用途 | 默认行为 |
|---|---|---|
| `ACP_DATABASE_URL` | Alembic、`acp-index` 和 Context API 使用的数据库连接 | 固定 ASGI 入口和 `acp-index` 写库时必填 |
| `ACP_ENV` | 运行环境标识 | 默认 `local` |
| `ACP_LOG_LEVEL` | 应用日志级别 | 默认 `INFO` |
| `ACP_SQL_ECHO` | SQLAlchemy SQL 日志开关 | 默认 `false` |
| `ACP_DEFAULT_REPO` | Context API 默认注入的 code repo filter | 默认不注入；应与 `acp-index --repo` 使用同一值 |
| `ACP_REQUIRE_REPO_FILTER` | 是否要求 search/build-task-context 必须带 repo | 默认 `false`；为 `true` 时请求或 `ACP_DEFAULT_REPO` 必须提供 repo |
| `ACP_ALIAS_FILE` | 领域词 alias JSON 文件路径 | 可选；用于把中文业务词扩展到代码符号、表名或文档表达 |
| `ACP_CONTEXT_API_BASE_URL` | MCP wrapper 调用 Context API 的地址 | 默认 `http://127.0.0.1:8000` |
| `ACP_MCP_TRANSPORT` | `acp-mcp-server` transport | 默认 `stdio`；remote MCP 只支持 `streamable-http` |
| `ACP_MCP_HOST` | remote MCP HTTP host | 默认 `127.0.0.1` |
| `ACP_MCP_PORT` | remote MCP HTTP port | 默认 `8001`，必须是 `1..65535` |
| `ACP_MCP_PATH` | remote MCP HTTP endpoint path | 默认 `/mcp`，必须以 `/` 开头 |
| `ACP_MCP_LOG_FILE` | MCP JSONL 调试日志路径 | 默认不写；父目录必须已存在 |
| `ACP_MCP_LOG_PAYLOADS` | 是否写完整 tool arguments 和 result | 默认 `false` |
| `ACP_EMBEDDING_PROVIDER` | embedding provider | 可选 `openai` 或 `infer`；不填时默认 `openai` |
| `ACP_EMBEDDING_BASE_URL` / `ACP_EMBEDDING_API_KEY` / `ACP_EMBEDDING_MODEL` / `ACP_EMBEDDING_DIMENSION` / `ACP_EMBEDDING_BATCH_SIZE` | embedding 配置组 | 如果填写其中任意一项，则必须整组填写；`openai` 会自动使用 `/embeddings`，`infer` 必须填完整 `/infer` endpoint |

## 快速开始

1. 复制配置样例：

   ```powershell
   Copy-Item .env.example .env
   ```

2. 编辑 `.env`，至少确认 `ACP_DATABASE_URL` 指向可用 PostgreSQL / pgvector 数据库。需要写入 embedding 时，确认 `ACP_EMBEDDING_PROVIDER`、`ACP_EMBEDDING_BASE_URL`、`ACP_EMBEDDING_API_KEY`、`ACP_EMBEDDING_MODEL`、`ACP_EMBEDDING_DIMENSION` 和 `ACP_EMBEDDING_BATCH_SIZE` 已配置。

3. 设置本仓库本地依赖缓存：

   ```powershell
   $env:UV_CACHE_DIR = ".uv-cache"
   $env:UV_PYTHON_INSTALL_DIR = ".uv-python"
   ```

4. 安装依赖：

   ```powershell
   uv sync --extra test
   ```

5. 将 `.env` 加载到当前 PowerShell 进程并执行迁移：

   ```powershell
   Get-Content .env | ForEach-Object {
       if ($_ -and -not $_.TrimStart().StartsWith("#") -and $_.Contains("=")) {
           $name, $value = $_.Split("=", 2)
           Set-Item -Path "Env:$($name.Trim())" -Value $value.Trim().Trim('"')
       }
   }
   uv run alembic upgrade head
   ```

6. 运行测试：

   ```powershell
   uv run --extra test pytest
   ```

7. 初始化工程索引。先 dry-run，再写入与 Context API 相同的 `ACP_DATABASE_URL`：

   ```powershell
   uv run acp-index --root D:\Code\YourProject --dry-run
   uv run acp-index --root D:\Code\YourProject --repo gitlab.example.com/group/project
   ```

   参数含义：

   - `--root` 是本次运行要扫描的本机工作区根目录，可以因电脑或 checkout 目录不同而变化。
   - `--repo` 是写入数据库的稳定 code repo identity，生产使用中应传入规范化后的 `gitlab.example.com/group/project`。不要把带 token、用户名或 `.git` 后缀的原始 remote URL 直接写入索引。
   - `--path` 是相对 `--root` 的 repo 内文件或目录 scope。推荐使用相对路径；root 内绝对路径只适合本机临时调用，不适合脚本或跨机器复用。

   如需手动增量重建指定文件或目录，可重复传入 `--path`。增量索引会按 `file_hash` 跳过未变化文件，并只清理同 repo、同 scope 且符合 include/exclude 的旧索引：

   ```powershell
   uv run acp-index --root D:\Code\YourProject --repo gitlab.example.com/group/project --path src/main/java/example
   uv run acp-index --root D:\Code\YourProject --repo gitlab.example.com/group/project --path docs/payment.md --dry-run
   ```

   常见覆盖场景：

   - 新增文件：传入新增文件或所在目录即可写入新索引，例如 `--path src/main/java/example/NewService.java`。
   - 修改文件：传入该文件即可覆盖同 repo、同 path 的旧 item，例如 `--path src/main/java/example/PaymentService.java`。
   - 删除文件：需要传入能覆盖旧 path 的 scope，例如删除 `src/main/java/example/PaymentService.java` 后运行 `--path src/main/java/example`，旧 item 才会被清理。
   - 文件移动：只传入新路径只会写入新 item；还需要传入旧路径所在目录，或传入共同上级目录，例如 `--path src/main/java`。
   - 整个 repo 换目录：只需改变 `--root`，保持同一个 `--repo` 和 repo 内相对 `--path`。例如从 `D:\Code\YourProject` 换到 `E:\Work\YourProject` 后继续运行 `--root E:\Work\YourProject --repo gitlab.example.com/group/project --path src/main/java/example`。

   如需同时写入 embedding，必须补齐 embedding 配置并显式开启：

   ```powershell
   uv run acp-index --root D:\Code\YourProject --repo gitlab.example.com/group/project --with-embedding
   ```

   也可以把索引所需配置直接放到 CLI 参数里，减少新手对 `.env` 加载顺序的依赖：

   ```powershell
   uv run acp-index `
     --root D:\Code\YourProject `
     --repo gitlab.example.com/group/project `
     --database-url "$env:ACP_DATABASE_URL" `
     --with-embedding `
     --embedding-provider "$env:ACP_EMBEDDING_PROVIDER" `
     --embedding-base-url "$env:ACP_EMBEDDING_BASE_URL" `
     --embedding-api-key "$env:ACP_EMBEDDING_API_KEY" `
     --embedding-model "$env:ACP_EMBEDDING_MODEL" `
     --embedding-dimension "$env:ACP_EMBEDDING_DIMENSION" `
     --embedding-batch-size "$env:ACP_EMBEDDING_BATCH_SIZE"
   ```

8. 启动 Context API：

   ```powershell
   uv run uvicorn agent_context_platform.asgi:app --host 127.0.0.1 --port 8000 --env-file .env
   ```

9. 启动 local stdio MCP wrapper：

   ```powershell
   $env:ACP_CONTEXT_API_BASE_URL = "http://127.0.0.1:8000"
   uv run acp-mcp-server
   ```

   如需 remote MCP HTTP：

   ```powershell
   $env:ACP_CONTEXT_API_BASE_URL = "http://127.0.0.1:8000"
   $env:ACP_MCP_TRANSPORT = "streamable-http"
   $env:ACP_MCP_HOST = "127.0.0.1"
   $env:ACP_MCP_PORT = "8001"
   $env:ACP_MCP_PATH = "/mcp"
   uv run acp-mcp-server
   ```

   Agent 侧 remote MCP URL 是 `http://127.0.0.1:8001/mcp`。`ACP_CONTEXT_API_BASE_URL` 仍然只是 MCP wrapper 调用 Context API 的地址。

## 当前运行边界

固定 ASGI 入口位于 `agent_context_platform.asgi:app`。运行配置由 `agent_context_platform.runtime` 统一加载；缺少 `ACP_DATABASE_URL`、日志级别格式错误、repo 严格模式缺少 repo filter 或 embedding provider 配置不完整时，会在启动或请求阶段明确失败。

MCP server 是 Context API 的包装层。它依赖可访问的 HTTP 服务，不直接访问 repository、SQLAlchemy session 或数据库。

真实项目入库入口是离线批处理命令 `acp-index`，不是 Context API 或 MCP server 的一部分。`acp-index` 支持 `dry-run`、include/exclude、显式 repo 标识、`--path` 手动增量索引、`--database-url` CLI 覆盖、embedding CLI 参数覆盖和 JSON 摘要；摘要包含 `scope_paths`、`files_changed`、`files_unchanged`、`files_deleted`、`items_deleted`、`symbols_deleted`、`branch`、`commit_sha`、`indexed_at`、`index_batch_id` 和 `provenance_warnings`。embedding 写入必须显式传入 `--with-embedding`。

同一数据库可以保存多个 GitLab code repo 的索引；`indexed_items`、`item_embeddings` 和 `symbols` 都按 repo 隔离。升级到 repo-scoped identity 或 symbol catalog schema 后，历史索引数据需要重新执行 `acp-index` 重建，不做旧数据归属猜测。

MCP JSONL 调试日志默认关闭。开启 `ACP_MCP_LOG_FILE` 后，日志记录 FastMCP 完成 schema 解析后的 tool name、structured arguments 摘要、Context API 返回摘要、错误和耗时；它不抓 raw JSON-RPC wire frame。只有 `ACP_MCP_LOG_PAYLOADS=true` 时才写完整 payload。

切换 embedding model 或 dimension 时，必须使用匹配的 `item_embeddings` 向量空间，不能混用不同向量空间。

## 本地验证

### 基础验证

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test pytest
```

### 阶段 0 归档样本回归

该脚本用于保留阶段 0 的历史回归能力，不是正式测评文档：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test python scripts/run_mvp_evaluation.py
```

默认样本路径为 `docs/archive/mvp/evaluation/mvp-evaluation-samples.json`。

### MCP 包装层验证

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test pytest tests/test_mcp_server.py
```

### pgvector 排序验证

该验证不依赖外部 embedding provider：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
$env:ACP_DATABASE_URL = "postgresql+psycopg://postgres@localhost:55432/agent_context_platform_mvp_pgvector"
uv run alembic upgrade head
uv run --extra test python scripts/verify_mvp_pgvector_search.py
```

### embedding 写入验证

该验证会真实调用当前配置的 embedding provider：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test python scripts/verify_mvp_embeddings.py --env-file .env
```

## 后续待办

- 阶段 1：生产化建设计划待确认。
- 正式测评体系待确认，见 [正式测评待办](docs/evaluation/evaluation-todo.md)。
- 公开部署 remote MCP 前需单独确认 HTTPS、认证和反向代理边界。
