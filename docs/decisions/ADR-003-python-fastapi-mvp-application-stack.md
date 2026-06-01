# ADR-003: Python FastAPI MVP Application Stack

## Status

Accepted

## Date

2026-05-12

## Context

MVP 已确定以 `build-task-context` 为首个验收工作流，并使用 PostgreSQL + pgvector、Hybrid Search、离线索引和 MCP Tool 接入。

后续实现需要选择应用主语言、HTTP 框架、数据库访问方式、Java/SQL/Markdown parser 和 embedding provider 边界。LLM 不属于当前 MVP 的检索必需依赖，后续如引入摘要、解释或评测辅助，再单独确认接入方式。

核心约束：

- 本地可运行优先。
- 索引器、评测脚本、HTTP API 和 MCP wrapper 需要共享模型与配置。
- MCP wrapper 不能复制业务逻辑，只能调用 Context API。
- Java 解析首版只需要结构化抽取，不做完整语义分析和调用链分析。
- 当前 MVP 不依赖 LLM；LLM 与 embedding 必须分开选择，embedding 是 Hybrid Search 的核心依赖。

## Decision

MVP 应用栈使用 Python。

具体选择：

- HTTP API：FastAPI。
- 数据模型与校验：Pydantic。
- 数据访问与迁移：SQLAlchemy、Alembic、psycopg。
- MCP 接入：MCP Python SDK。
- Java parser：tree-sitter-java。
- SQL parser：sqlglot。
- Markdown parser：markdown-it-py，并补充 line range glue code。
- LLM：当前 MVP 不接入；后续如需要摘要、解释或评测辅助，再选择 OpenAI-compatible 外部服务。
- Embedding：独立外部 EmbeddingProvider，不与 LLM 默认绑定。
- 本地数据库：本机安装 PostgreSQL 和 pgvector extension，不以 Docker Compose 作为默认开发路径。

Embedding provider 必须通过配置注入，至少包含：

- `base_url`
- `api_key`
- `model`
- `dimension`
- `batch_size`

PostgreSQL `vector` 维度必须与 embedding 模型维度一致。更换 embedding 模型时，默认需要重建索引。

## Alternatives Considered

### Java / Spring Boot

Pros:

- Java AST 和企业 Java 生态契合度高。
- 后续接入 Java 项目语义分析更自然。

Cons:

- 离线索引、评测脚本、embedding 接入和 MCP glue code 更重。
- MVP 当前重点不是构建企业 Java 服务框架。

Rejected because MVP 需要更快验证上下文召回质量和 Agent 接入链路。

### Node.js / TypeScript

Pros:

- MCP 和 Web 工具生态较好。
- TypeScript 类型系统适合定义 API contract。

Cons:

- Python 在数据处理、评测脚本、parser glue code 和 embedding 接入上更直接。
- PostgreSQL、向量检索和离线批处理脚本会更依赖额外工具组合。

Rejected because Python 更符合当前 MVP 的 glue code 需求。

### JavaParser for Java Indexing

Pros:

- Java AST 能力更强。
- 对 Java 语义和签名解析更完整。

Cons:

- 需要额外 JVM 工具链或跨进程集成。
- MVP 首版只需要 class、method、annotation、signature 和 line range 抽取。

Rejected for MVP. 如果 tree-sitter-java 无法满足真实样本，再引入 JavaParser 作为增强索引器。

### 本地 embedding 模型

Pros:

- 数据边界更可控。
- 不依赖外部 embedding 服务。

Cons:

- 本机部署、模型管理和性能验证会扩大 MVP 工作量。
- CPU/GPU 环境差异会影响本地可运行性。

Rejected for MVP. 首版使用外部 EmbeddingProvider，但保留可替换边界。

## Consequences

- 项目代码结构应围绕 Python package、FastAPI app、indexer modules、evaluation scripts 和 MCP wrapper 组织。
- `.gitignore` 需要覆盖 Python 虚拟环境、缓存、coverage、构建产物和本地数据库产物。
- 数据库迁移必须进入版本控制，不能依赖手工 SQL 状态。
- Embedding 模型维度是 schema 约束，变更时要显式重建索引。
- 如果后续引入 JavaParser 或本地 embedding，应新增 ADR 或更新本 ADR 的 superseding decision。
