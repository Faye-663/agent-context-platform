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
- LLM 使用 OpenAI-compatible 外部服务；embedding 独立选择外部 EmbeddingProvider。
- 召回质量必须通过固定评测集验证。

## 阶段 1：基础能力

### 任务 1：定义公共模型与来源引用模型

**说明：** 使用 Pydantic 定义 `IndexedItem`、`SourceCitation`、`SearchResult`、`TaskContext` 的代码模型、校验规则和序列化格式。

**验收标准：**

- [ ] 模型字段与 [Context API 契约](../api/context-api.md) 对齐。
- [ ] 代码、SQL、Markdown 三类来源都能用 `SourceCitation` 表示。
- [ ] 缺失来源引用的结果无法通过模型校验。

**验证方式：**

- [ ] 模型单元测试覆盖三类资产。
- [ ] JSON 序列化结果与接口文档示例语义一致。

**依赖：** 无

**预估范围：** 中

### 任务 2：建立存储结构与迁移

**说明：** 使用 SQLAlchemy、Alembic 和 psycopg 建立 PostgreSQL 表结构，用于保存索引项、结构化元数据、来源引用和嵌入向量。

**验收标准：**

- [ ] 可以保存 `IndexedItem` 和 `SourceCitation`。
- [ ] 可以按 `asset_type`、`path`、`language`、`symbol_type`、`table` 过滤。
- [ ] pgvector 字段可用于向量检索。

**验证方式：**

- [ ] 迁移可在空数据库执行成功。
- [ ] 存储层测试可以插入并读取三类资产样本。

**依赖：** 任务 1

**预估范围：** 中

### 检查点：基础能力

- [ ] 公共模型稳定。
- [ ] 数据库迁移可重复执行。
- [ ] 三类资产样本可以写入并读取。

## 阶段 2：离线索引

### 任务 3：实现 Java 索引器

**说明：** 使用 tree-sitter-java 解析 Java 文件并抽取 class（类）、method（方法）、annotation（注解）、signature（签名）、file path（文件路径）和 line range（行号范围）。

**验收标准：**

- [ ] 能识别 class（类）和 method（方法）级索引项。
- [ ] 能保留 annotation（注解）和 signature（签名）。
- [ ] 每个索引项都有代码来源引用。

**验证方式：**

- [ ] 使用脱敏 Java 测试样本运行单元测试。
- [ ] 行号定位与测试样本断言一致。

**依赖：** 任务 1、任务 2

**预估范围：** 中

### 任务 4：实现 SQL 索引器

**说明：** 使用 sqlglot 解析 SQL DDL，抽取 table（表）、column（字段）、index（索引）和来源文件信息。

**验收标准：**

- [ ] 能识别表级索引项。
- [ ] 能识别字段级索引项。
- [ ] 能保留表名、字段名、索引和 DDL 来源。

**验证方式：**

- [ ] 使用脱敏 DDL 测试样本运行单元测试。
- [ ] 表级和字段级来源引用完整。

**依赖：** 任务 1、任务 2

**预估范围：** 中

### 任务 5：实现 Markdown 索引器

**说明：** 使用 markdown-it-py 解析 Markdown 标题层级和正文片段，补充 line range glue code，生成可检索文档索引。

**验收标准：**

- [ ] 能生成 heading path（标题路径）。
- [ ] 能保留 file path（文件路径）和 line range（行号范围）。
- [ ] 能按标题和正文生成索引内容。

**验证方式：**

- [ ] 使用脱敏 Markdown 测试样本运行单元测试。
- [ ] 多级标题下的正文归属正确。

**依赖：** 任务 1、任务 2

**预估范围：** 小

### 检查点：离线索引

- [ ] Java、SQL、Markdown 测试样本都能完成离线索引。
- [ ] 索引结果可写入数据库。
- [ ] 每条索引结果都有来源引用。

## 阶段 3：核心流程

### 任务 6：实现混合检索

**说明：** 实现关键词搜索、向量搜索和结构化过滤组合，并返回统一 `SearchResult`。

**验收标准：**

- [ ] 支持按资产类型过滤。
- [ ] 支持关键词和向量检索组合排序。
- [ ] 返回 `score`、可选 `score_parts` 和 `match_reason`。

**验证方式：**

- [ ] 使用固定测试样本验证关键词命中优先级。
- [ ] 使用固定测试样本验证结构化过滤不会跨资产污染结果。

**依赖：** 任务 2、任务 3、任务 4、任务 5

**预估范围：** 中

### 任务 7：实现 `search-code` / `search-db-schema` / `search-doc`

**说明：** 基于混合检索暴露三类检索接口。

**验收标准：**

- [ ] 三个接口的响应结构与 [Context API 契约](../api/context-api.md) 对齐。
- [ ] 每个结果都有 `SourceCitation`。
- [ ] 参数错误返回明确错误码。

**验证方式：**

- [ ] 接口测试覆盖正常查询、空结果、参数错误。
- [ ] 日志包含请求 ID、接口名称、返回数量和耗时。

**依赖：** 任务 6

**预估范围：** 中

### 任务 8：实现 `build-task-context`

**说明：** 聚合代码、表结构、文档和相似实现，返回 `TaskContext`。

**验收标准：**

- [ ] 会调用三类检索 API。
- [ ] 能分组返回 `related_code`、`related_db_schema`、`related_docs`、`similar_implementations`。
- [ ] 当上下文不足时返回 `missing_context` 或 `risks`。
- [ ] 不返回无来源引用的上下文。

**验证方式：**

- [ ] 集成测试覆盖完整召回、部分缺失、全部为空三种场景。
- [ ] 使用评测样本验证上下文包可读且可追溯。

**依赖：** 任务 7

**预估范围：** 中

### 检查点：核心流程

- [ ] 三类检索接口可用。
- [ ] `build-task-context` 完成端到端测试。
- [ ] 空结果和错误路径可诊断。

## 阶段 4：Agent 接入与评测

### 任务 9：实现 MCP 包装层

**说明：** 使用 MCP Python SDK 提供 MCP 工具，让 Agent 调用 Context API。

**验收标准：**

- [ ] MCP 工具入参与 HTTP 接口保持一致。
- [ ] MCP 包装层不直接访问数据库。
- [ ] 接口错误能透传为 Agent 可理解的错误信息。

**验证方式：**

- [ ] 本地 Agent 调用 `build-task-context` 成功。
- [ ] 模拟接口错误时 MCP 返回明确失败原因。

**依赖：** 任务 8

**预估范围：** 小

### 任务 10：建立固定评测集与回归脚本

**说明：** 准备 10-20 个真实或半真实工程任务样本，并建立可重复运行的召回评测。

**验收标准：**

- [ ] 每个样本包含任务描述、期望命中引用、无关结果判定规则。
- [ ] 能计算 Top5 命中率。
- [ ] 能记录 Top10 明显无关结果数量。

**验证方式：**

- [ ] 回归脚本可在本地运行。
- [ ] 评测输出包含通过/失败和失败样本详情。

**依赖：** 任务 8

**预估范围：** 中

### 检查点：Agent 接入

- [ ] Agent 可以通过 MCP 调用 `build-task-context`。
- [ ] 固定评测集可重复运行。
- [ ] Top5 命中率和 Top10 无关结果指标可被追踪。

## 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 解析器选型与真实项目语法不兼容 | 高 | 使用测试样本覆盖常见 Java/SQL/Markdown 结构，遇到真实样本再扩展 |
| 召回结果看似相关但工程上不可用 | 高 | 评测集必须标注期望来源引用，不只看自然语言相似 |
| MCP 和 HTTP 行为漂移 | 中 | MCP 只调用 HTTP 接口，不复制检索逻辑 |
| 嵌入模型服务不稳定 | 中 | embedding provider 可配置，错误路径必须可诊断 |
| MVP 范围膨胀 | 高 | 以 ADR 中排除项为准，新增范围需新增 ADR |

## 待确认问题

- 真实评测语料使用哪个脱敏 Java 项目。
- embedding 首版具体服务、模型名、向量维度和 batch size。
- OpenAI-compatible 外部 LLM 的 provider、模型名和配置方式。
- 本机 PostgreSQL 与 pgvector 的版本和安装校验命令。
