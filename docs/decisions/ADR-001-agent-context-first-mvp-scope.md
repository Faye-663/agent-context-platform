# ADR-001: Agent Context First MVP Scope

## Status

Accepted

## Date

2026-05-12

## Context

agent-context-platform 的原始目标是解决 AI Coding Agent 难以有效利用工程资产的问题。

如果 MVP 做成泛知识库或人工搜索台，系统会很快偏向“用户问一句，系统答一句”的传统 RAG 形态。这种形态对代码生成、方案设计和 Review 帮助有限，因为 Agent 真正需要的是可追溯、可组合、可继续检索的工程上下文。

首版必须先验证一个问题：

```text
Agent 能否通过工具调用拿到足够可靠的任务上下文。
```

## Decision

MVP 采用 Agent Context First 范围。

首个验收工作流固定为：

```text
build-task-context
```

第一版资产范围固定为：

- Java 代码。
- SQL 表结构。
- Markdown 文档。

MVP 不做：

- 人工搜索 UI。
- 泛知识库问答。
- PPT。
- PDF。
- 图片或流程图理解。
- GraphRAG。
- 实时索引。
- 权限系统。

所有返回结果必须包含来源引用。

## Alternatives Considered

### 人工搜索台优先

Pros:

- 更容易演示。
- 用户可以手动判断搜索结果。

Cons:

- 偏离 Agent Tool Layer 的核心场景。
- 容易把开发重点放到 UI 和交互，而不是上下文质量。
- 不能直接验证 Agent 是否能在正确时机获取正确上下文。

Rejected because MVP 的首要风险是 Agent 上下文召回质量，不是人工搜索体验。

### 泛知识库问答优先

Pros:

- 形态常见，容易理解。
- 可复用通用 RAG 方案。

Cons:

- 对代码场景效果有限。
- 容易返回无来源或弱来源的自然语言结论。
- 难以表达 class、method、table、heading path 等工程结构。

Rejected because 本项目的价值不在“存知识”，而在“让 Agent 获取工程上下文”。

### 覆盖更多资产类型

Pros:

- 文档覆盖面更完整。
- 更接近长期愿景。

Cons:

- PPT、PDF、图片解析会扩大测试面。
- 多模态和结构还原不是 MVP 核心风险。
- 范围变宽会稀释 Java/SQL/Markdown 的召回质量验证。

Rejected for MVP. These can be considered after core retrieval quality is measured.

## Consequences

- 后续实现必须优先交付 `build-task-context`。
- README、需求、架构、API 和评测文档都围绕 Agent 调用组织。
- 新增资产类型或 UI 前，应先确认 MVP 指标已达标。
- 如果要改变 MVP 范围，应新增 ADR，而不是直接改实现方向。
