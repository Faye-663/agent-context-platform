# agent-context-platform MVP 产品需求

## 背景

在使用 opencode、Codex、Claude Code 等 AI Coding Agent 做方案设计、代码修改、Review 和问题排查时，Agent 经常无法稳定利用企业内部工程资产。

典型问题包括：

- 大型存量代码仓无法完整放入上下文。
- 历史设计方案分散在 Markdown、PPT 或其他文档中。
- 数据库表结构与代码逻辑脱节。
- 简单 RAG 容易召回无关或过期内容。
- 多模块、多层级代码关系难以通过普通 prompt 描述清楚。

因此，本项目不做泛知识库，而是构建一个面向 Coding Agent 的工程上下文检索系统。

## 目标用户

MVP 面向两类用户：

- Coding Agent：通过 HTTP API 或 MCP Tool 主动检索上下文。
- 使用 Coding Agent 的工程师：希望 Agent 在设计、编码、Review 前先拿到正确工程背景。

## 核心问题

当用户提出类似下面的工程任务时：

```text
新增某银行支付接口，并复用已有 pain.001 生成能力
```

Agent 需要的不只是关键词搜索结果，而是一个可直接用于工程判断的上下文包：

- 相关 Service、Mapper、Converter、Parser。
- 相似银行或渠道实现。
- 相关 SQL 表结构和字段约束。
- 相关 Markdown 设计方案和开发规范。
- 潜在风险和缺失上下文。
- 每条结果的可追溯来源。

## MVP 目标

MVP 只验证一个核心能力：

```text
让 Coding Agent 可以调用 build-task-context 获取任务相关工程上下文。
```

成功的 MVP 应该做到：

- 找到相似实现，而不是只返回语义相近文本。
- 返回跨资产上下文，包括代码、表结构和设计文档。
- 为每条结果提供来源引用。
- 用固定评测集验证召回质量。

## 首个验收工作流

首个验收工作流固定为 `build-task-context`。

流程：

```text
用户提出工程任务
    ↓
Agent 调用 build-task-context
    ↓
系统内部调用 search-code / search-db-schema / search-doc
    ↓
系统聚合、排序、裁剪上下文
    ↓
返回 TaskContext
```

该工作流优先于人工搜索台、泛知识库问答和完整 UI。

## MVP 资产范围

| 类型 | 纳入内容 | 目的 |
|---|---|---|
| Java 代码 | class、method、annotation、signature、file path、line range | 支持相似实现和结构化代码定位 |
| SQL 表结构 | table、column、DDL、index | 支持数据模型与字段约束理解 |
| Markdown 文档 | heading path、正文片段、file path、line range | 支持设计方案和开发规范检索 |

## 初始化索引 CLI P0 需求

真实项目可用 MVP 需要一个通用离线 CLI，把工程资产初始化写入检索库。该 CLI 不属于查询链路；HTTP API 和 MCP server 继续只负责检索与上下文构建。

P0 范围固定为：

- 提供单一索引入口，例如 `acp-index --root <path>`，递归扫描一个工程目录。
- 复用运行时数据库配置，至少支持通过 `ACP_DATABASE_URL` 指向与 Context API 相同的 PostgreSQL / pgvector 数据库。
- 支持 `dry-run`，在不写库的情况下输出扫描文件数、可索引文件数和预计生成的 Java、SQL、Markdown 索引项数量。
- 支持 include / exclude 规则，默认排除 `.git`、`target`、`build`、`dist`、`node_modules`、`.venv`、`__pycache__` 等非工程资产目录。
- 支持显式 repo 标识；未传入时可以使用根目录名，但必须在输出中打印最终使用的 repo。
- 执行结束输出可排查摘要，至少包含 repo、database、files scanned、files indexed、items written、items failed、embedding written 和 elapsed time。

P0 不要求：

- 实时索引或 watch mode。
- 复杂增量同步。
- HTTP ingest endpoint。
- 多仓库关联。
- 独立配置文件格式。

## Remote MCP HTTP 需求

当前 local MCP 通过 stdio 启动 `acp-mcp-server`，再由 MCP wrapper 调用 Context API。为支持远程 Agent 直接通过 MCP URL 接入，MVP 支持 remote MCP over HTTP。

P0 范围固定为：

- 保留 local stdio MCP 作为默认启动方式，现有本地 Agent 配置不需要迁移。
- remote MCP 只支持 HTTP `streamable-http` transport，不支持 SSE。
- remote MCP 暴露独立 MCP URL，例如 `http://127.0.0.1:8001/mcp` 或部署后的 `https://<domain>/mcp`。
- `ACP_CONTEXT_API_BASE_URL` 继续表示 MCP wrapper 调用后端 Context API 的地址，不能作为 Agent 侧 remote MCP URL。
- remote MCP 继续复用 `search_code`、`search_db_schema`、`search_doc` 和 `build_task_context` 工具，不复制检索、上下文构建或数据库访问逻辑。
- remote MCP 的 host、port、path 必须可配置，并且默认不与 Context API 的 `127.0.0.1:8000` 监听地址冲突。

P0 不要求：

- SSE transport。
- 完整权限系统。
- 将 MCP endpoint 和 Context API 强制挂在同一个端口或同一个 ASGI app 下。
- 新增独立检索逻辑、HTTP ingest endpoint 或数据库直连路径。

## MCP 调试日志需求

调试和固定评测时，工程师需要复盘 Agent 实际调用了哪个 MCP tool、传入了什么结构化参数、Context API 返回了什么结果或错误，以及单次调用耗时。MVP 需要提供服务端可落盘的 MCP 调试日志，避免只能依赖 Agent 侧界面或临时终端输出判断问题。

P0 范围固定为：

- 提供可选 JSONL 日志文件配置；未显式配置时，`acp-mcp-server` 不写 MCP 调试日志。
- 每次 MCP tool 调用记录 tool name、request id、调用状态、耗时和轻量摘要，便于定位空召回、错误返回和慢调用。
- “真实 Agent 请求”以 FastMCP 完成 schema 解析后的 tool name 和 structured arguments 为准；P0 不抓 raw JSON-RPC wire frame。
- 默认不记录完整请求和完整返回正文，避免把 task、query、source content 或 metadata 默认落盘。
- 仅在显式 debug / evaluation 开关启用时，允许写入完整 tool arguments 和 tool result payload。
- stdio MCP 下不得向 stdout 写调试内容，避免破坏 MCP JSON-RPC 消息流。

P0 不要求：

- 通过 MCP logging notification 向 Agent 侧实时推送日志。
- 持久化 raw JSON-RPC 协议帧。
- 日志轮转、压缩、采样或集中式日志上报。
- 对 payload 内容做字段级脱敏；开启完整 payload 日志前由调用方确认运行环境和数据边界。

## 明确排除项

| 不做项 | 原因 |
|---|---|
| PPT | 第一版先控制解析和评测复杂度 |
| PDF | 解析质量和结构还原不稳定 |
| 图片 / 流程图理解 | 多模态成本高，非 MVP 核心风险 |
| GraphRAG | 关系抽取复杂，错误关系会污染结果 |
| 实时索引 | 离线重建已能验证核心价值 |
| 权限系统 | MVP 先在内部验证环境中运行 |
| 人工搜索 UI | 首个工作流是 Agent Tool，不是人工检索 |
| 泛知识库问答 | 容易偏离工程上下文系统定位 |
| SSE remote MCP | remote MCP 首版只验证 HTTP `streamable-http`，减少 transport 分支和兼容性风险 |

## 成功标准

MVP 通过固定评测集验收。

基础指标：

- Top5 命中率 >= 70%。
- Top10 明显无关结果 <= 3 条。
- 所有结果必须包含来源引用。

上下文完整性要求：

- 对典型代码生成任务，应尽量返回相关代码、表结构、设计文档和相似实现。
- 当上下文不足时，系统应明确暴露缺失项，而不是伪造结论。

## 约束

- 示例数据必须脱敏，不写入真实企业内部标识。
- 文档和接口命名保留必要技术英文，例如 `Hybrid Search`、`TaskContext`、`MCP`。
- 后续实现涉及具体框架 API 时，必须以官方文档为准，不凭记忆实现。
- remote MCP 对外暴露前必须单独确认 HTTPS、认证和反向代理边界；P0 只承诺受控环境内的 HTTP MCP 可用性验证。
