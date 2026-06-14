# agent-context-platform 当前架构设计

## 架构目标

系统目标是让 Coding Agent 在执行工程任务前，可以按需获取可信、相关、可引用的工程上下文。当前架构以 Context API 为稳定内核，MCP 和 CLI 是围绕该内核的接入与初始化入口。

## 总体结构

```text
Coding Agent
    |
    | HTTP API / MCP Tool
    v
Context API Server
    |
    v
HybridSearchService + TaskContextBuilder
    |
    v
IndexedItemRepository
    |
    v
PostgreSQL + pgvector

Index CLI
    |
    v
Java / SQL / Markdown Indexers
    |
    v
IndexedItemRepository + Symbol Catalog + optional EmbeddingProvider
```

## 入口

| 入口 | 代码位置 | 职责 |
|---|---|---|
| Context API | `agent_context_platform.asgi:app` / `api.py` | 暴露 HTTP 检索和任务上下文接口 |
| Runtime 装配 | `runtime.py` | 从 `ACP_*` 环境变量装配 engine、session、repository、embedding provider 和 FastAPI app |
| MCP server | `mcp_server.py` / `acp-mcp-server` | 暴露 Agent Tool，调用 Context API |
| Index CLI | `index_cli.py` / `acp-index` | 扫描工程目录、解析资产、写入索引和可选 embedding |

## Context API

`api.py` 提供四个 HTTP endpoint：

- `POST /search-code`
- `POST /search-db-schema`
- `POST /search-doc`
- `POST /build-task-context`

三个 search endpoint 共享 `SearchRequest`：

- `query`：必填，非空。
- `limit`：默认 `10`，范围 `1..50`。
- `filters`：支持 `repo`、`language`、`symbol_type`、`path_prefix`、`table`。
- `query_embedding`：可选；用于调用方显式提供 query embedding。
- `request_id`：可选；不传时 API 自动生成。

`build-task-context` 使用 `BuildTaskContextRequest`：

- `task`：必填，非空。
- `limits`：按资产类型控制返回数量。
- `constraints`：当前主要用于 `repo`、`language` 等跨检索约束。
- `request_id`：可选。

`constraints.token_budget` 可选控制 `build-task-context` 返回上下文规模；超出预算时优先保留更靠前的检索证据，并通过 `missing_context` / `risks` 暴露被裁剪后的上下文缺口。

API 层只负责请求校验、错误 envelope 和日志包装，检索由 `HybridSearchService` 执行，上下文检索编排由 `TaskContextBuilder` 执行，结果裁剪、缺口判断、风险和 citation 汇总由 `ContextComposer` 执行。

## 数据模型

核心模型定义在 `models.py`：

- `IndexedItem` 表示可检索工程资产。
- `SourceCitation` 表示来源坐标。
- `SearchResult` 表示一次检索命中。
- `TaskContext` 表示给 Agent 的任务上下文包。
- `SymbolCatalogEntry` 表示 Java / SQL declaration symbol，用于后续 symbol recall 和 code graph 节点身份。

`SourceCitation` 除了 repo、path、line range、symbol/table/heading 等定位字段，还保存索引来源 provenance：best-effort Git branch / commit、文件 SHA-256、索引时间和索引批次 ID。当前 `repo` 用作 GitLab code repo identity 和 multi code repo 共库隔离键；非 Git 目录或无法读取 Git 信息时，branch / commit 允许为空，索引流程继续执行。

模型强制约束：

- `asset_type` 必须与 `source.source_type` 一致。
- code/doc 来源必须包含 path 和行号。
- db_schema 来源必须包含 table。
- `SearchResult.source` 必须与 `item.source` 一致。
- `TaskContext.citations` 必须覆盖所有返回结果来源。

## 检索与存储

`HybridSearchService` 组合 lexical、vector 和 symbol 多路召回，并使用 RRF 融合候选。lexical 召回使用工程 tokenization 和 BM25-like 字段加权，覆盖中文、camelCase / PascalCase、snake_case、路径、表名、字段名和 symbol。中文分词优先使用 `jieba` search mode，并把领域词 / 工程词加入词典；无分词器时保留最长匹配和 2-4 gram 规则 fallback。vector 召回在 provider/model/dimension 明确时由 repository 层使用 PostgreSQL / pgvector 执行 query embedding 相似度排序；SQLite 路径保留为单元测试和轻量验证替代实现。symbol 召回消费 `symbols` catalog，并按 `(repo, item_id)` 与其他通道去重。

`IndexedItemRepository` 保存：

- `indexed_items`：工程资产、结构化 metadata 和来源字段；存储身份为 `(repo, id)`。
- `item_embeddings`：按 `repo`、item id、provider、model、dimension 和 task identity 保存 embedding。
- `symbols`：按 `(repo, symbol_id)` 保存 Java / SQL symbol definitions；`source_item_id` 指向同 repo 下可展示或可检索的 `IndexedItem`。

查询和写入必须使用匹配的 embedding identity，避免不同向量空间混用。

symbol catalog 只保存 definitions，不保存 method call、field access、type reference、extends / implements 等 graph edge。当前检索层会读取 symbol catalog 做 exact / prefix / lightweight fuzzy recall，并把命中原因写入 `SearchResult.match_reason` 和内部 retrieval trace。

领域词别名通过可选 `ACP_ALIAS_FILE` 配置加载，格式为 `{"aliases":[{"term":"现金流审批","expands_to":["cashflow approval","PaymentApprovalService"]}]}`。未配置时不做 query expansion；配置后 alias expansion 会进入检索 tokenization 和内部 trace。

检索可以通过 `repo` filter 限定候选集。未传 repo 时保持兼容的跨 repo 搜索；如果运行时开启 `ACP_REQUIRE_REPO_FILTER`，请求必须携带 repo 或由 `ACP_DEFAULT_REPO` 注入。

## 索引流程

`acp-index` 是真实项目入库入口。它负责：

- 递归扫描 `--root`；`--root` 是本机工作区根目录，不写入为跨机器身份。
- 应用 include/exclude；传入 `--path` 时只扫描指定文件或目录 scope。`--path` 推荐使用相对 `--root` 的 repo 内路径，持久化到 `SourceCitation.path` 的也是该相对路径。
- 使用根目录名或 `--repo` 生成 repo 标识；生产使用应显式传入规范化 GitLab code repo identity。`--repo` 是跨机器、跨 checkout 目录复用同一批索引的稳定隔离键。
- 生成本次运行的索引批次 ID 和索引时间。
- best-effort 读取 `--root` 的 Git branch / commit；读取失败时记录 provenance warning，不阻断索引。
- 按原始文件 bytes 计算 SHA-256，写入每条来源引用。
- 调用 Java、SQL、Markdown indexer。
- 为 Java class / interface / enum / record / annotation type / method / constructor / field，以及 SQL table / column 写入 symbol catalog。
- 使用已存 file hash 判断 changed / unchanged；hash 未变化的文件不重写 item 或 embedding。
- 清理同 repo、同 scope 且符合 include/exclude 的旧索引和旧 symbols；删除文件或移动文件时，调用方需要传入覆盖旧 path 的 scope，否则旧 path 不会被清理。读取或解析失败的文件保留旧索引。
- 在 `--dry-run` 时只输出扫描和预计索引摘要，不写入或删除数据库记录。
- 在非 `dry-run` 时复用 `ACP_DATABASE_URL` 写库。
- 仅在 `--with-embedding` 时调用外部 provider 并写入 embedding。

CLI 输出 JSON 摘要，字段包括 `repo`、`database`、`scope_paths`、`files_scanned`、`files_indexed`、`files_changed`、`files_unchanged`、`files_deleted`、`items_estimated`、`symbols_estimated`、`items_written`、`symbols_written`、`items_deleted`、`symbols_deleted`、`items_failed`、`embedding_written`、`branch`、`commit_sha`、`indexed_at`、`index_batch_id`、`provenance_warnings`、`elapsed_seconds` 和 `failures`。

## MCP 接入

`acp-mcp-server` 默认使用 local stdio MCP。remote MCP 通过以下配置启用：

- `ACP_MCP_TRANSPORT=streamable-http`
- `ACP_MCP_HOST`
- `ACP_MCP_PORT`
- `ACP_MCP_PATH`

MCP wrapper 只通过 `ContextApiToolClient` 调用 Context API，不直连 repository、SQLAlchemy session 或数据库。`ACP_CONTEXT_API_BASE_URL` 是 wrapper 调用 Context API 的地址；Agent 侧 remote MCP URL 是 MCP server 暴露的独立 endpoint。

## 配置边界

运行配置由 `runtime.py` 和 `mcp_server.py` 从进程环境变量读取。应用不会自动加载 `.env`；`uvicorn --env-file .env` 只影响 Uvicorn 进程，不影响 Alembic 或 `acp-index`。

关键配置：

- `ACP_DATABASE_URL`
- `ACP_ENV`
- `ACP_LOG_LEVEL`
- `ACP_SQL_ECHO`
- `ACP_DEFAULT_REPO`
- `ACP_REQUIRE_REPO_FILTER`
- `ACP_ALIAS_FILE`
- `ACP_CONTEXT_API_BASE_URL`
- `ACP_MCP_TRANSPORT`
- `ACP_MCP_HOST`
- `ACP_MCP_PORT`
- `ACP_MCP_PATH`
- `ACP_MCP_LOG_FILE`
- `ACP_MCP_LOG_PAYLOADS`
- `ACP_EMBEDDING_PROVIDER`
- `ACP_EMBEDDING_BASE_URL`
- `ACP_EMBEDDING_API_KEY`
- `ACP_EMBEDDING_MODEL`
- `ACP_EMBEDDING_DIMENSION`
- `ACP_EMBEDDING_BATCH_SIZE`
- `ACP_EMBEDDING_DOCUMENT_TASK`
- `ACP_EMBEDDING_QUERY_TASK`

## 当前限制

- 不提供实时索引或 HTTP ingest。
- 不提供权限系统。
- 不支持 SSE MCP transport。
- 不解析 PPT、PDF、图片或流程图。
- 不实现 GraphRAG 或完整调用链图谱。
- 正式测评体系仍待设计，阶段 0 评测材料只作为历史参考。
