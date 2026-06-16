# 阶段摘要

## 背景

agent-context-platform 的目标是让 Coding Agent 在改代码前，能拿到可信、相关、可引用的工程上下文，而不是只依赖当前窗口里的局部代码。

这次 Phase 1 的重点不是做一个完整知识库产品，而是补齐工程检索主链路：

```text
真实工程材料
  -> 离线索引
  -> repo / provenance / symbol catalog
  -> lexical / vector / symbol 多路召回
  -> RRF 融合
  -> context package
  -> MCP / API / Playground / evaluation
```

## 当前完成情况

当前 `master` 已具备以下能力：

- Java、SQL DDL、Markdown 离线索引。
- repo-scoped 存储身份，支持多 code repo 共库隔离。
- provenance：repo、branch、commit、file hash、index time、batch id。
- manual incremental indexing：按 `--path` 重建和清理。
- symbol catalog：Java / SQL declarations 存储、清理和读取。
- 中文词级 lexical retrieval，支持 `jieba` search mode、工程词典和 fallback。
- alias expansion：中文业务词映射代码符号、表名、文档表达。
- lexical / vector / symbol 多路召回，RRF 融合。
- Context Composer：token budget、missing context、待确认项、citations。
- Context API 和 MCP wrapper。
- evaluation harness、golden tasks、`acp-eval` CLI。
- MCP Web Playground，用于直接调试 MCP tools 和查看响应。

## 当前验证

本地全量测试：

```text
uv run pytest
130 passed, 2 skipped
```

跳过项是 live regression，需要真实 Context API 服务运行在 `http://127.0.0.1:8000`。

## 当前判断

Phase 1 主链路已经基本完成，完成度约 80%-85%。

剩余工作集中在：

- 用真实项目数据跑 evaluation。
- 把详细 retrieval trace 接入 API / Playground。
- 调整 BM25、RRF、alias、sufficiency 参数。
- 明确 symbol catalog 中 graph-only symbol 和 recall symbol 的边界。

## 总体结论

当前项目已经具备继续推进真实项目验证的基础，不再只是 Swagger 上几个接口。下一阶段应该用真实工程数据评估召回质量，而不是继续无边界扩功能。
