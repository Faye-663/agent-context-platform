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
