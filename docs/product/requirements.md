# agent-context-platform 正式需求

## 背景

agent-context-platform 面向 AI Coding Agent，目标是在方案设计、代码修改、Review 和问题排查前，为 Agent 提供可信、相关、可引用的工程上下文。

本需求文档按正式生产级项目维护，描述当前产品和工程边界。项目后续围绕生产级使用所需的稳定性、可运维性、可评测性和可演进性推进。

## 当前进展

阶段 0：MVP 开发与验收已完成。Phase 1 基础能力已基本合入 `master`，当前进入真实数据验证、trace 打通和效果调优阶段。后续生产化建设计划仍待正式确认。

## 目标用户

- Coding Agent：通过 Context API 或 MCP Tool 主动检索工程上下文。
- 使用 Coding Agent 的工程师：希望 Agent 在设计、编码、Review 前先拿到可靠工程背景。
- 平台维护者：需要可诊断、可验证、可部署的上下文检索服务。

## 当前能力基线

当前 master 已具备以下能力：

- Java、SQL DDL、Markdown 离线索引。
- `IndexedItem`、`SourceCitation`、`SearchResult`、`TaskContext` 公共模型。
- PostgreSQL / pgvector 存储，SQLite 保留为测试路径。
- 索引来源 provenance：repo、best-effort branch / commit、file hash、index time 和 index batch。
- Multi code repo 共库隔离：indexed item 和 embedding 按 repo 隔离，检索支持 repo filter。
- Symbol catalog：Java / SQL symbol definitions 按 repo 隔离保存，为 symbol recall 和 code graph 铺底。
- lexical、vector、symbol 多路召回，RRF 融合和统一 `SearchResult`。
- 中文 lexical retrieval：`jieba` search mode、工程词典、alias expansion 和无分词器 fallback。
- Context Composer：token budget、`missing_context`、待确认项和 citation 汇总。
- Context API：`/search-code`、`/search-db-schema`、`/search-doc`、`/build-task-context`。
- DebugOptions：search / build-task-context 支持 `debug_options.include_trace`。
- MCP wrapper：`search_code`、`search_db_schema`、`search_doc`、`build_task_context`。
- Evaluation harness：`eval/golden-tasks.json`、`acp-eval` CLI 和回归测试入口。
- MCP Web Playground：开发调试入口。
- 固定 ASGI 入口：`agent_context_platform.asgi:app`。
- 初始化索引 CLI：`acp-index --root <path>`。
- Embedding provider：OpenAI-compatible `/v1/embeddings` 和 message-style `/infer`。
- Remote MCP HTTP：`ACP_MCP_TRANSPORT=streamable-http`。
- MCP JSONL 调试日志：默认关闭，可显式输出摘要或完整 payload。

## 正式需求

### 1. 稳定接口

- Context API 是稳定内核，MCP wrapper 只能调用 Context API，不直接访问数据库或复制检索逻辑。
- API 返回结果必须包含可追溯 `SourceCitation`；不能把无来源自然语言包装成工程事实。
- `SourceCitation` 应支持 repo、best-effort branch / commit、file hash、index time 和 index batch，用于判断来源新鲜度和索引批次边界。
- `repo` 当前表示 GitLab code repo identity；同一个 `IndexedItem.id` 只在单个 repo 内唯一。
- Context API 应支持 `filters.repo` 和 `constraints.repo`；严格模式下缺少 repo 必须返回明确参数错误。
- `request_id` 应贯穿 HTTP、MCP 调试日志和错误定位。
- `query_embedding` 仅作为 `debug_options` 中的显式调用能力，用于测试或上游已生成 query embedding 的场景。

### 2. 可控索引

- 真实工程入库只能通过离线批处理入口 `acp-index` 完成。
- `acp-index` 必须支持 `dry-run`、include/exclude、显式 repo 标识、按 `--path` 手动增量索引和 JSON 摘要。
- `--root` 表示本机扫描根目录，允许在不同电脑或不同 checkout 目录变化；生产索引应显式传入稳定的 GitLab code repo 标识 `--repo`，不能依赖本地目录名表达多仓隔离。
- `--path` 表示相对 `--root` 的 repo 内文件或目录 scope；跨机器脚本应使用相对路径，不应把本机绝对路径作为长期配置。
- `acp-index` 必须为成功索引的 item 写入 file hash、index time 和 index batch；Git branch / commit 以 best-effort 方式采集，采集失败不得阻断非 Git 样本或普通索引。
- `acp-index` 必须为 Java class / interface / enum / record / annotation type / method / constructor / field，以及 SQL table / column 写入独立 symbol catalog；catalog 只记录 definitions，不记录 graph edges。
- `acp-index --path` 必须只清理同 repo、同 scope 且符合 include/exclude 的旧索引和旧 symbols；失败文件保留旧索引，避免解析偶发失败导致证据丢失。
- `acp-index` 默认不调用外部 embedding provider；只有显式传入 `--with-embedding` 才写入 embedding。
- Alembic 和 `acp-index` 只读取当前进程环境变量，不自动加载 `.env`。

### 3. 向量空间隔离

- item embedding 必须按 provider、model 和 dimension 隔离。
- 查询和写入必须使用匹配的向量空间，不能混用不同 provider、model 或 dimension。
- provider 配置不完整、维度不匹配或 provider 调用失败时必须明确失败，不静默降级。

### 4. Agent 接入

- local MCP 默认使用 stdio，保持本地 Agent 接入路径稳定。
- remote MCP 只支持 HTTP `streamable-http`，不支持 SSE。
- `ACP_CONTEXT_API_BASE_URL` 表示 MCP wrapper 调用的 Context API 地址，不是 Agent 侧 remote MCP URL。
- remote MCP 对外暴露前必须单独确认 HTTPS、认证和反向代理边界。

### 5. 可观测与调试

- Context API 必须记录 request id、API name、结果数量、耗时和错误码。
- 默认日志不记录敏感 task/query 全文。
- MCP JSONL 调试日志默认关闭；开启完整 payload 前必须确认运行环境和数据边界。
- stdio MCP 下调试内容不得写入 stdout，避免破坏 MCP JSON-RPC 消息流。

## 非目标

阶段 1：生产化建设的具体路线图待定。除非后续需求明确确认，当前正式需求不承诺：

- 人工搜索 UI。
- 泛知识库问答。
- PPT、PDF、图片或流程图解析。
- GraphRAG。
- 实时索引或 watch mode。
- HTTP ingest endpoint。
- 完整权限系统。
- SSE MCP transport。
- 多仓库关联与跨仓依赖图谱。
- doc/code/sql 与 organization 之间的业务归属或多对多适用关系。

## 待确认项

- 阶段 1：生产化建设计划与优先级。
- 正式测评体系、真实语料、指标和报告格式。
- 生产部署形态、认证方式、HTTPS / reverse proxy 边界。
- 真实项目 SQL 方言覆盖范围。
- 多仓库隔离、权限与数据保留策略。
