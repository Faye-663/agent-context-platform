# agent-context-platform MVP 架构设计

## 架构目标

MVP 架构服务于一个目标：

```text
让 Coding Agent 能够按需获取可信、相关、可引用的工程上下文。
```

系统不以人工搜索 UI 为中心，也不以泛知识库问答为中心。稳定内核是 Context API，Agent 可以通过 HTTP 或 MCP Tool 调用它。

## 总体架构

```text
opencode / Codex / Claude Code
        |
        | HTTP API / MCP Tool
        v
Context API Server
        |
        | calls
        v
Context Builder
        |
        +-- search-code
        +-- search-db-schema
        +-- search-doc
        |
        v
Index Store: PostgreSQL + pgvector
        ^
        |
Index CLI (offline batch)
        |
        v
Offline Indexers
        |
        +-- Java Indexer
        +-- SQL Indexer
        +-- Markdown Indexer
```

## 技术栈

MVP 技术栈以 Python glue code 为主，优先降低本地开发、离线索引、评测和 Agent 接入的集成成本。应用栈选择见 [ADR-003](../decisions/ADR-003-python-fastapi-mvp-application-stack.md)。

| 层级 | 技术 | 说明 |
|---|---|---|
| 应用语言 | Python | Context API、索引器、评测脚本和 MCP 包装层使用同一主语言，减少跨语言集成成本。 |
| HTTP API | FastAPI、Pydantic | FastAPI 暴露稳定 HTTP API；Pydantic 定义请求、响应、错误和内部公共模型。 |
| Agent 接入 | HTTP API、MCP Tool | HTTP API 是稳定内核；MCP Tool 只做 Agent 接入适配，不复制业务逻辑。 |
| MCP 接入 | MCP Python SDK | MCP 工具只调用 Context API，不直接访问数据库。 |
| 数据访问与迁移 | SQLAlchemy、Alembic、psycopg | SQLAlchemy 负责数据库访问边界；Alembic 管理 schema 迁移；psycopg 连接 PostgreSQL。 |
| 检索存储 | PostgreSQL + pgvector | 保存结构化元数据、来源引用、可检索文本和 embedding，支持关键词、向量和结构化过滤组合检索。 |
| 检索策略 | Hybrid Search | 组合关键词搜索、向量搜索、结构化过滤、排序与去重。 |
| Java 解析 | tree-sitter-java | 首版抽取 package、class、method、annotation、signature 和 line range；复杂语义分析后置。 |
| SQL 解析 | sqlglot | 首版解析 SQL DDL，抽取 table、column、index 和来源信息。 |
| Markdown 解析 | markdown-it-py + line range glue code | 使用成熟 Markdown parser 处理标题和正文结构，补充行号定位逻辑。 |
| 索引模式 | Offline Indexing | MVP 使用离线索引和手动重建，不做实时增量索引。 |
| 初始化入口 | Index CLI | 真实项目入库通过离线批处理 CLI 完成；HTTP API 和 MCP server 不承担初始化入库职责。 |
| LLM | OpenAI-compatible 外部服务 | LLM 不作为检索必须依赖，后续可用于摘要、解释或评测辅助。 |
| Embedding | DashScope native / OpenAI-compatible EmbeddingProvider | embedding 与 LLM 分开选择；provider 通过 `provider`、`base_url`、`api_key`、`model`、`dimension`、`batch_size` 配置，Jina 可额外配置 document/query task mode。 |
| 本地依赖 | 本机 PostgreSQL、pgvector extension | 本地开发默认使用本机安装，不把 Docker Compose 作为默认路径。 |

Embedding 首版使用 DashScope native 多模态 embedding API，阶段五补充 OpenAI-compatible provider 以支持 OpenAI/Jina 风格 `/v1/embeddings`。因为向量维度与 embedding 模型绑定，系统按 provider、model、dimension 独立保存 embedding；查询和写入必须使用匹配的 provider/model/dimension/task identity，不能混用不同向量空间。

## 数据流

### 离线索引流程

```text
工程资产
    ↓
Index CLI 扫描 root、应用 include/exclude、确定 repo 标识
    ↓
Java / SQL / Markdown Indexer
    ↓
结构化解析
    ↓
生成 IndexedItem + SourceCitation
    ↓
生成 embedding
    ↓
写入 PostgreSQL + pgvector item_embeddings
```

MVP 使用离线索引，不做实时增量索引。这样可以先验证召回质量和上下文组织方式，避免把复杂度投入到非核心链路。

Index CLI 是离线批处理编排层，负责把文件扫描、索引器、repository 和可选 embedding 写入串起来。P0 必须支持 `dry-run`、include/exclude、复用 `ACP_DATABASE_URL`、稳定 repo 标识和结果摘要；不在 P0 中实现实时监听、复杂增量同步或 HTTP 入库接口。

### 查询流程

```text
Agent query
    ↓
Context API
    ↓
关键词检索 + 向量检索 + 结构化过滤
    ↓
排序与去重
    ↓
Context Builder 聚合上下文
    ↓
返回 TaskContext
```

## 核心模块

### Context API Server

职责：

- 暴露首版 HTTP API。
- 校验请求参数。
- 调用检索服务和 Context Builder。
- 返回统一的响应结构。
- 输出必要日志，便于定位查询、召回和裁剪问题。

HTTP API 是稳定内核。MCP Server 只作为 Agent 接入层，不应复制业务逻辑。

### MCP Tool Layer

职责：

- 将 Agent 的 Tool Calling 转换为 Context API 调用。
- 保持入参和出参与 HTTP API 对齐。
- 不直接访问数据库。

这样可以避免 HTTP 和 MCP 两套行为漂移。

### Java Indexer

职责：

- 解析 Java 文件。
- 抽取 package、class、method、annotation、signature、file path、line range。
- 为 class/method 生成可检索文本。
- 保留符号级来源引用。

MVP 不做完整调用链分析。调用关系可以作为后续增强能力，但不能阻塞首版。

### SQL Indexer

职责：

- 解析 DDL 文件。
- 抽取 table、column、index、comment、source file。
- 保留表级和字段级来源引用。
- 支持按业务词、表名、字段名检索。

MVP 不要求理解运行时 ORM 映射，只先建立可检索的表结构上下文。

### Markdown Indexer

职责：

- 解析 Markdown 标题层级和正文片段。
- 生成 heading path。
- 保留 file path 和 line range。
- 支持设计方案、开发规范、历史说明检索。

MVP 不处理 PPT、PDF 和图片。

### Index Store

职责：

- 存储结构化元数据。
- 存储原始可检索文本摘要。
- 按 provider、model、dimension 存储 embedding。
- 支持关键词检索、向量检索和结构化过滤。

MVP 使用 PostgreSQL + pgvector，避免引入额外搜索集群和图数据库。

### Context Builder

职责：

- 调用 `search-code`、`search-db-schema`、`search-doc`。
- 合并不同来源结果。
- 去重、排序、裁剪 token。
- 组织相似实现、相关表结构、相关文档和风险提示。
- 当某类上下文缺失时显式标记缺失。

`build-task-context` 是 MVP 最关键能力。

## 检索策略

MVP 采用 `Hybrid Search`：

```text
关键词搜索
+ 向量搜索
+ 结构化过滤
+ 排序与去重
```

原因：

- 代码场景中类名、方法名、表名、字段名非常关键。
- 单纯 embedding 容易召回语义相近但工程上无关的内容。
- 结构化过滤可以限制语言、资产类型、路径、符号类型等范围。

MVP 阶段不要求引入复杂 rerank 模型。可以先用可解释的加权排序实现，后续根据评测结果替换。

## 存储边界

PostgreSQL 保存：

- IndexedItem 基础字段。
- SourceCitation 来源引用。
- asset type、language、symbol type、repo、path 等过滤字段。
- 可检索正文或摘要。
- item embedding 向量和对应 provider/model/dimension。

PostgreSQL 不负责：

- 直接理解 Java AST。
- 动态解析 Git 历史。
- 管理权限系统。
- 承担 GraphRAG 的图推理能力。

## 设计原则

- 先结构化，后图谱。
- 先离线重建，后增量索引。
- 先评测召回质量，后扩展资产类型。
- 先 HTTP API 稳定内核，后 MCP 接入适配。
- 每条上下文必须可引用，不能只返回自然语言总结。

## 风险

| 风险 | 影响 | 应对 |
|---|---|---|
| Java 解析质量不足 | 相似实现召回不稳定 | 先覆盖 class/method/annotation/signature，不做完整调用链 |
| 向量结果无关 | Agent 被错误上下文误导 | Hybrid Search 必须保留关键词和结构化过滤 |
| 文档过期 | 返回不可信设计背景 | MVP 先返回来源，后续再做可信度标记 |
| 上下文过长 | Agent 无法有效使用 | Context Builder 必须裁剪并分组 |
| 缺少评测集 | 无法判断是否可用 | 先建立固定评测集，再调优 |
