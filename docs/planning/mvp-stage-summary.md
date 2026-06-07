# MVP 阶段总结

## 阶段定位

agent-context-platform 的 MVP 阶段已经完成验收。该阶段目标是验证 Coding Agent 可以通过稳定接口获取可信、相关、可引用的工程上下文，并证明核心链路可以从离线索引、混合检索、Context API、MCP 接入运行到固定评测回归。

MVP 文档已归档到 [MVP 阶段归档](../archive/mvp/README.md)。这些资料保留历史背景和验证证据，不再作为正式 Pro 开发阶段的当前需求或架构入口。

## 已完成能力

- 公共模型：`IndexedItem`、`SourceCitation`、`SearchResult`、`TaskContext` 已落地，并强制保留来源引用。
- 离线索引：Java、SQL DDL、Markdown 三类资产可解析为结构化索引项。
- 存储与迁移：SQLAlchemy repository、Alembic 迁移、PostgreSQL / pgvector 存储边界已建立，SQLite 路径保留为轻量测试路径。
- 混合检索：支持关键词、向量、结构化过滤、有界合并和统一 `SearchResult`。
- Context API：提供 `/search-code`、`/search-db-schema`、`/search-doc`、`/build-task-context`。
- MCP 接入：`acp-mcp-server` 通过 MCP Python SDK 暴露同等工具，包装层只调用 Context API，不直接访问数据库。
- 运行入口：`agent_context_platform.asgi:app` 支持长期运行 Context API，`runtime` 统一解析数据库、日志和 embedding 配置。
- Embedding：支持 DashScope native、OpenAI-compatible 和 Jina task mode，`item_embeddings` 按 provider/model/dimension/task identity 隔离向量空间。
- 初始化索引：`acp-index --root <path>` 支持 `dry-run`、include/exclude、显式 repo、复用 `ACP_DATABASE_URL` 和显式 `--with-embedding`。
- Remote MCP：支持 `ACP_MCP_TRANSPORT=streamable-http`，默认 local stdio MCP 保持不变。
- 调试观测：MCP 可选 JSONL 调试日志支持摘要和显式 payload 模式，stdio 下不写 stdout。

## 验收结论

MVP 验收结论采用当前正式文档口径：MVP 已完成，项目进入正式 Pro 开发阶段。

归档验证记录中保留了各阶段的测试、脚本和人工验证证据，包括全量单元测试、固定评测集回归、PostgreSQL / pgvector 验证、DashScope/Jina embedding 验证、初始化索引 CLI 验证和 remote MCP HTTP 验证。正式阶段后续测评体系需要重新设计，不直接把 MVP 评测计划扩展为正式测评文档。

## 转入 Pro 阶段的边界

- 正式需求入口改为 [正式需求](../product/requirements.md)。
- 当前架构入口改为 [当前架构设计](../architecture/design.md)。
- 正式开发计划待定；本次归档不定义 Pro 阶段路线图。
- 正式测评体系待优化，当前只记录 [正式测评待办](../evaluation/evaluation-todo.md)。
- ADR 保持不变；新增长期架构决策时再创建新的 ADR。
