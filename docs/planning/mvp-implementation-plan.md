# MVP 实施计划

## 概述

本计划将本项目 MVP 拆成可独立验证的任务。实施顺序遵循依赖关系：先定义公共模型，再做离线索引和存储，之后实现检索、上下文构建器、MCP 接入和评测调优。

## 架构决策

- HTTP 接口是稳定内核，MCP 包装层只做 Agent 接入适配。
- MVP 应用栈使用 Python、FastAPI、Pydantic。
- 数据访问和迁移使用 SQLAlchemy、Alembic、psycopg。
- MVP 资产范围固定为 Java、SQL、Markdown。
- Java 解析首版使用 tree-sitter-java，复杂语义分析后置。
- SQL DDL 解析首版使用 sqlglot。
- Markdown 解析首版使用 markdown-it-py，并补充 line range glue code。
- MVP 使用离线索引，不做实时增量。
- MVP 使用 PostgreSQL + pgvector，不引入 Milvus、Neo4j、OpenSearch。
- PostgreSQL 和 pgvector 本地开发默认使用本机安装。
- 当前 MVP 不依赖 LLM；embedding 独立选择外部 EmbeddingProvider。后续如引入摘要、解释或评测辅助，再单独确认 OpenAI-compatible LLM 配置。
- MCP 包装层默认继续支持本地 stdio；remote MCP 只使用 HTTP `streamable-http` transport，不实现 SSE。
- 召回质量必须通过固定评测集验证。

## 阶段 1：基础能力

### 任务 1：定义公共模型与来源引用模型

**说明：** 使用 Pydantic 定义 `IndexedItem`、`SourceCitation`、`SearchResult`、`TaskContext` 的代码模型、校验规则和序列化格式。

**验收标准：**

- [x] 模型字段与 [Context API 契约](../api/context-api.md) 对齐。
- [x] 代码、SQL、Markdown 三类来源都能用 `SourceCitation` 表示。
- [x] 缺失来源引用的结果无法通过模型校验。

**验证方式：**

- [x] 模型单元测试覆盖三类资产。
- [x] JSON 序列化结果与接口文档示例语义一致。

**依赖：** 无

**预估范围：** 中

### 任务 2：建立存储结构与迁移

**说明：** 使用 SQLAlchemy、Alembic 和 psycopg 建立 PostgreSQL 表结构，用于保存索引项、结构化元数据、来源引用和嵌入向量。

**验收标准：**

- [x] 可以保存 `IndexedItem` 和 `SourceCitation`。
- [x] 可以按 `asset_type`、`path`、`language`、`symbol_type`、`table` 过滤。
- [x] pgvector 字段可用于向量检索。

**验证方式：**

- [x] 迁移可在空数据库执行成功。
- [x] 存储层测试可以插入并读取三类资产样本。

**依赖：** 任务 1

**预估范围：** 中

### 检查点：基础能力

- [x] 公共模型稳定。
- [x] 数据库迁移可重复执行。
- [x] 三类资产样本可以写入并读取。

## 阶段 2：离线索引

### 任务 3：实现 Java 索引器

**说明：** 使用 tree-sitter-java 解析 Java 文件并抽取 class（类）、method（方法）、annotation（注解）、signature（签名）、file path（文件路径）和 line range（行号范围）。

**验收标准：**

- [x] 能识别 class（类）和 method（方法）级索引项。
- [x] 能保留 annotation（注解）和 signature（签名）。
- [x] 每个索引项都有代码来源引用。

**验证方式：**

- [x] 使用脱敏 Java 测试样本运行单元测试。
- [x] 行号定位与测试样本断言一致。

**依赖：** 任务 1、任务 2

**预估范围：** 中

### 任务 4：实现 SQL 索引器

**说明：** 使用 sqlglot 解析 SQL DDL，抽取 table（表）、column（字段）、index（索引）和来源文件信息。

**验收标准：**

- [x] 能识别表级索引项。
- [x] 能识别字段级索引项。
- [x] 能保留表名、字段名、索引和 DDL 来源。

**验证方式：**

- [x] 使用脱敏 DDL 测试样本运行单元测试。
- [x] 表级和字段级来源引用完整。

**依赖：** 任务 1、任务 2

**预估范围：** 中

### 任务 5：实现 Markdown 索引器

**说明：** 使用 markdown-it-py 解析 Markdown 标题层级和正文片段，补充 line range glue code，生成可检索文档索引。

**验收标准：**

- [x] 能生成 heading path（标题路径）。
- [x] 能保留 file path（文件路径）和 line range（行号范围）。
- [x] 能按标题和正文生成索引内容。

**验证方式：**

- [x] 使用脱敏 Markdown 测试样本运行单元测试。
- [x] 多级标题下的正文归属正确。

**依赖：** 任务 1、任务 2

**预估范围：** 小

### 检查点：离线索引

- [x] Java、SQL、Markdown 测试样本都能完成离线索引。
- [x] 索引结果可写入数据库。
- [x] 每条索引结果都有来源引用。

阶段二实际验证记录见 [阶段二实际验证记录](phase-2-verification.md)。当前验证覆盖真实文件落盘、离线索引、SQLite repository 写读和关键来源字段断言；尚未覆盖真实 PostgreSQL + pgvector 的离线写入链路。

## 阶段 3：核心流程

### 任务 6：实现混合检索

**说明：** 实现关键词搜索、向量搜索和结构化过滤组合，并返回统一 `SearchResult`。

**验收标准：**

- [x] 支持按资产类型过滤。
- [x] 支持关键词和向量检索组合排序。
- [x] 返回 `score`、可选 `score_parts` 和 `match_reason`。

**验证方式：**

- [x] 使用固定测试样本验证关键词命中优先级。
- [x] 使用固定测试样本验证结构化过滤不会跨资产污染结果。

**依赖：** 任务 2、任务 3、任务 4、任务 5

**预估范围：** 中

### 任务 7：实现 `search-code` / `search-db-schema` / `search-doc`

**说明：** 基于混合检索暴露三类检索接口。

**验收标准：**

- [x] 三个接口的响应结构与 [Context API 契约](../api/context-api.md) 对齐。
- [x] 每个结果都有 `SourceCitation`。
- [x] 参数错误返回明确错误码。

**验证方式：**

- [x] 接口测试覆盖正常查询、空结果、参数错误。
- [x] 日志包含请求 ID、接口名称、返回数量和耗时。

**依赖：** 任务 6

**预估范围：** 中

### 任务 8：实现 `build-task-context`

**说明：** 聚合代码、表结构、文档和相似实现，返回 `TaskContext`。

**验收标准：**

- [x] 会调用三类检索 API。
- [x] 能分组返回 `related_code`、`related_db_schema`、`related_docs`、`similar_implementations`。
- [x] 当上下文不足时返回 `missing_context` 或 `risks`。
- [x] 不返回无来源引用的上下文。

**验证方式：**

- [x] 集成测试覆盖完整召回、部分缺失、全部为空三种场景。
- [x] 使用固定测试样本验证上下文包可读且可追溯。

**依赖：** 任务 7

**预估范围：** 中

### 检查点：核心流程

- [x] 三类检索接口可用。
- [x] `build-task-context` 完成端到端测试。
- [x] 空结果和错误路径可诊断。

阶段三实际验证记录见 [阶段三实际验证记录](phase-3-verification.md)。当前验证覆盖 SQLite repository、混合检索排序、FastAPI 接口契约、参数错误、查询日志、`build-task-context` 聚合，以及真实 PostgreSQL + pgvector 写读和运行时检索路径；尚未覆盖外部 EmbeddingProvider 和数据库侧 pgvector 相似度排序。

## 阶段 4：Agent 接入与评测

### 任务 9：实现 MCP 包装层

**说明：** 使用 MCP Python SDK 提供 MCP 工具，让 Agent 调用 Context API。

**验收标准：**

- [x] MCP 工具入参与 HTTP 接口保持一致。
- [x] MCP 包装层不直接访问数据库。
- [x] 接口错误能透传为 Agent 可理解的错误信息。

**验证方式：**

- [x] 本地 Agent 调用 `build-task-context` 成功。
- [x] 模拟接口错误时 MCP 返回明确失败原因。

**依赖：** 任务 8

**预估范围：** 小

### 任务 10：建立固定评测集与回归脚本

**说明：** 准备 10-20 个真实或半真实工程任务样本，并建立可重复运行的召回评测。

**验收标准：**

- [x] 每个样本包含任务描述、期望命中引用、无关结果判定规则。
- [x] 能计算 Top5 命中率。
- [x] 能记录 Top10 明显无关结果数量。

**验证方式：**

- [x] 回归脚本可在本地运行。
- [x] 评测输出包含通过/失败和失败样本详情。

**依赖：** 任务 8

**预估范围：** 中

### 检查点：Agent 接入

- [x] Agent 可以通过 MCP 调用 `build-task-context`。
- [x] 固定评测集可重复运行。
- [x] Top5 命中率和 Top10 无关结果指标可被追踪。

阶段四实际验证记录见 [阶段四实际验证记录](phase-4-verification.md)。当前验证覆盖 MCP `FastMCP` 工具注册、`build-task-context` 工具调用、Context API 错误透传、10 个固定脱敏评测样本、Top5 命中率、Top10 明显无关结果数量和来源引用完整率；尚未覆盖真实脱敏 Java 项目索引库、外部 EmbeddingProvider 和数据库侧 pgvector 相似度排序。

## 阶段 5：真实可用 MVP 收口

阶段四已经证明 MVP 骨架、Context API、MCP 包装层和固定样本回归可以跑通。阶段五用于补齐真实项目可用前的缺口；完成前不能把当前状态视为真实项目 MVP 验收完成。

### 任务 11：固定 ASGI 入口与运行配置加载

**说明：** 提供面向长期运行 HTTP 服务的固定 ASGI 入口，并集中加载数据库、日志、embedding provider 和运行环境配置。

**验收标准：**

- [x] 仓库提供稳定的 ASGI app 导入路径，用于 `uvicorn` 或同类 ASGI server 启动。
- [x] 配置加载器可以读取 `ACP_DATABASE_URL`、embedding provider 配置和必要运行参数。
- [x] 配置缺失或格式错误时返回明确异常和日志，不在启动后静默失败。

**验证方式：**

- [x] 本地通过固定 ASGI 入口启动 Context API。
- [x] 使用真实 PostgreSQL / pgvector 连接执行 `/search-code`、`/search-db-schema`、`/search-doc` 和 `/build-task-context` 的冒烟验证。
- [x] 缺失关键配置时有可定位错误信息。

**依赖：** 任务 8、任务 9

**预估范围：** 中

### 任务 12：外部 EmbeddingProvider 与批量 embedding 写入

**说明：** 接入独立外部 EmbeddingProvider，为离线索引结果批量生成 embedding，并写入按 provider、model、dimension 区分的 `item_embeddings`。

**验收标准：**

- [x] 支持通过配置指定 embedding provider 的 `base_url`、`api_key`、`model`、`dimension` 和 `batch_size`。
- [x] 批量写入流程能为 Java、SQL、Markdown 三类索引项生成并保存 embedding。
- [x] embedding 维度与当前 provider/model/dimension 不匹配时明确失败，避免不同向量空间混用。
- [x] provider 调用失败时输出必要日志，便于定位请求失败、限流或模型配置错误。

**验证方式：**

- [x] 使用脱敏样本完成一次离线索引、embedding 生成和落库验证。
- [x] 单元测试覆盖配置校验、维度不匹配和 provider 失败路径。
- [x] 集成验证确认查询侧能使用生成的 query embedding 和 item embedding。

阶段五实际验证记录见 [阶段五实际验证记录](phase-5-verification.md)。当前实现不把数据库列固定为 `vector(768)`；embedding 按模型身份存入 `item_embeddings`，以兼容不同 embedding model 的维度。

**依赖：** 任务 2、任务 3、任务 4、任务 5、任务 11

**预估范围：** 中

### 任务 13：数据库侧 pgvector 相似度排序

**说明：** 将向量相似度排序下推到 PostgreSQL / pgvector，避免应用侧全量拉取候选后计算余弦相似度。

**验收标准：**

- [x] repository 层支持基于 query embedding 的 pgvector 相似度查询。
- [x] 混合检索仍保留关键词分数、向量分数、结构化过滤和统一 `SearchResult`。
- [x] `limit` 和结构化过滤在数据库查询阶段生效，避免无界候选扫描。
- [x] SQLite 测试路径保留轻量替代实现，不阻塞单元测试。

**验证方式：**

- [x] 单元测试覆盖排序、过滤、空 embedding 和维度异常路径。
- [x] PostgreSQL / pgvector 集成验证确认相似度排序来自数据库查询。
- [x] 固定评测集回归指标不低于阶段四结果。

阶段五实际验证记录见 [阶段五实际验证记录](phase-5-verification.md)。当前实现会在 provider/model/dimension 明确时使用 PostgreSQL / pgvector 的 `<=>` 相似度排序；SQLite 路径保留应用侧轻量排序用于单元测试。

**依赖：** 任务 6、任务 12

**预估范围：** 中

### 任务 14：真实项目初始化索引 CLI P0

**说明：** 提供面向真实工程目录的离线初始化索引 CLI，把 Java、SQL、Markdown 文件扫描、索引器解析、repository 写入和可选 embedding 写入串成一个可重复执行的入口。

**验收标准：**

- [x] 提供稳定命令入口，例如 `acp-index --root <path>`。
- [x] 复用 `ACP_DATABASE_URL`，确保 CLI 写入的数据库与 Context API 读取的数据库一致。
- [x] 支持 `dry-run`，不写库时输出扫描文件数、可索引文件数和预计索引项数量。
- [x] 支持 include / exclude 规则，并默认排除 `.git`、`target`、`build`、`dist`、`node_modules`、`.venv`、`__pycache__`。
- [x] 支持显式 repo 标识；未传入时使用根目录名，并在摘要中打印最终 repo。
- [x] 完成后输出 repo、database、files scanned、files indexed、items written、items failed、embedding written 和 elapsed time。

**验证方式：**

- [x] 使用临时样本目录验证 Java、SQL、Markdown 三类文件会被扫描、解析并写入 repository。
- [x] `dry-run` 不产生数据库写入。
- [x] include / exclude 能稳定过滤目标文件和构建产物目录。
- [x] CLI 输出摘要可用于定位失败文件和确认写入边界。

阶段五实际验证记录见 [阶段五实际验证记录](phase-5-verification.md)。当前 CLI 固定为 `acp-index`，支持 `dry-run`、include/exclude、显式 repo 标识、复用 `ACP_DATABASE_URL` 写入 repository；embedding 只有显式传入 `--with-embedding` 时才会写入。

**非目标：**

- [ ] 不实现实时索引或 watch mode。
- [ ] 不实现复杂增量同步。
- [ ] 不新增 HTTP ingest endpoint。
- [ ] 不引入独立配置文件格式。

**依赖：** 任务 2、任务 3、任务 4、任务 5、任务 11、任务 12

**预估范围：** 中

### 任务 15：真实脱敏 Java 项目索引库召回评测

**说明：** 选择一个真实脱敏 Java 项目，完成 Java、SQL、Markdown 离线索引、embedding 写入和 `build-task-context` 召回评测。

**验收标准：**

- [ ] 真实评测语料来源已确认并完成脱敏，不写入真实企业内部标识。
- [ ] 离线索引覆盖真实项目中的 Java、SQL 和 Markdown 资产。
- [ ] 评测样本基于真实工程任务编写，并标注期望命中来源和明显无关判定规则。
- [ ] Top5 命中率、Top10 明显无关结果数量和来源引用完整率达到 MVP 成功标准。

**验证方式：**

- [ ] 对真实脱敏项目执行完整离线索引和 embedding 写入。
- [ ] 运行固定评测脚本并输出通过 / 失败、失败样本详情和关键指标。
- [ ] 抽查 `build-task-context` 返回的来源引用可以定位到真实脱敏项目文件、行号、表或文档章节。

**依赖：** 任务 11、任务 12、任务 13、任务 14

**预估范围：** 中

### 任务 16：Remote MCP over HTTP

**说明：** 在保留默认 local stdio MCP 的前提下，为远程 Agent 接入提供 HTTP MCP endpoint。remote MCP 只支持 MCP SDK 的 `streamable-http` transport；MCP server 仍然只调用 Context API，不直接访问数据库或 repository。

**验收标准：**

- [ ] `acp-mcp-server` 默认启动方式保持 stdio，现有 local MCP 配置无需迁移。
- [ ] 可通过配置显式启用 HTTP remote MCP，例如 `ACP_MCP_TRANSPORT=streamable-http`。
- [ ] remote MCP 暴露独立 HTTP endpoint，例如 `/mcp`；该 URL 与 `ACP_CONTEXT_API_BASE_URL` 明确区分。
- [ ] 支持配置 remote MCP 的 host、port 和 path，默认不与 Context API 的 `127.0.0.1:8000` 抢占同一监听端口。
- [ ] 不支持 `sse` transport；配置为 `sse` 或其他未知 transport 时启动失败并给出明确错误。
- [ ] remote MCP 仍复用现有 `search_code`、`search_db_schema`、`search_doc` 和 `build_task_context` 工具定义，不复制检索逻辑。

**验证方式：**

- [ ] 单元测试覆盖默认 stdio、HTTP remote 配置解析、非法 transport 和非法端口 / path。
- [ ] 使用 `streamable-http` 启动 remote MCP，验证 Agent 或 MCP client 可以通过 `/mcp` 完成 `list_tools`。
- [ ] 对 remote MCP 调用 `build_task_context`，确认返回真实 Context API 结果且错误路径可诊断。
- [ ] README 或运行文档明确区分 local stdio MCP、remote MCP URL 和 Context API URL。

**非目标：**

- [ ] 不实现 SSE remote MCP。
- [ ] 不改变 local stdio 的默认行为。
- [ ] 不把 `ACP_CONTEXT_API_BASE_URL` 暴露为 Agent 需要填写的 MCP server URL。
- [ ] 不新增独立检索逻辑或数据库访问路径。
- [ ] 不在本任务内实现完整权限系统；公开互联网部署前需单独确认认证、HTTPS 和反向代理边界。

**依赖：** 任务 9、任务 11

**预估范围：** 小

### 检查点：真实可用 MVP 收口

- [x] Context API 可以通过固定 ASGI 入口长期运行。
- [x] 真实项目初始化索引 CLI 可以扫描工程目录、写入索引并生成可排查摘要。
- [x] 真实索引流程可以生成并保存 embedding。
- [x] 检索在 PostgreSQL / pgvector 侧完成向量相似度排序。
- [ ] 真实脱敏 Java 项目评测达到 MVP 成功标准。
- [ ] Remote MCP HTTP endpoint 可以被 Agent 或 MCP client 调用。

## 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 解析器选型与真实项目语法不兼容 | 高 | 使用测试样本覆盖常见 Java/SQL/Markdown 结构，遇到真实样本再扩展 |
| 真实语料包含当前非目标 SQL 方言 | 中 | MySQL dump 兼容不作为任务 15 前置待办；如果语料包含 jshERP 这类 MySQL dump，需要先重新确认验收范围或转换输入语料 |
| 召回结果看似相关但工程上不可用 | 高 | 评测集必须标注期望来源引用，不只看自然语言相似 |
| MCP 和 HTTP 行为漂移 | 中 | MCP 只调用 HTTP 接口，不复制检索逻辑 |
| Remote MCP 暴露后被误认为 Context API 或绕过部署边界 | 中 | 文档和配置明确区分 remote MCP URL、Context API URL 和 local stdio；公开部署前单独确认认证与 HTTPS |
| 嵌入模型服务不稳定 | 中 | embedding provider 可配置，错误路径必须可诊断；当前支持 DashScope native、OpenAI-compatible 和 Jina task mode，查询和写入必须使用匹配的 provider/model/dimension/task identity |
| MVP 范围膨胀 | 高 | 以 ADR 中排除项为准，新增范围需新增 ADR |

## 待确认问题

- 真实评测语料使用哪个脱敏 Java 项目。
- Remote MCP 首个验证环境使用本机回环地址、内网主机，还是带 HTTPS 的远程域名。
