# P1 检索与上下文组装实现进展

## 归属范围

本文记录开发者 C 负责的检索与上下文组装能力的首版实现进展，对应 Phase 1 并行开发计划中的：

- `P1-T7: Lexical Retrieval / Tokenizer / BM25`
- `P1-T8: Domain Vocabulary / Alias Mapping`
- `P1-T10: Retrieval / Multi-Recall / RRF / Trace`
- `P1-T11: Context Composer / Token Budgeting`
- `P1-T12: Context Sufficiency / Confidence`
- `P1-T9: Symbol Index` 的 retrieval 接入部分

## 当前进度

首版代码实现已完成，整体进度约 `80%`。

已完成部分覆盖主链路能力：query 进入 Context API 后，可以经过 alias expansion、lexical / vector / symbol 多路召回、RRF 融合，再由 Context Composer 输出带引用的 TaskContext。

剩余 `20%` 主要是效果调优和评测建设，不是主链路阻塞项：

- BM25 字段权重、RRF `k` 值和 per-channel limit 需要结合真实任务集调参。
- retrieval trace 目前是内部结构，暂未作为正式 API response 暴露。
- sufficiency / confidence 目前采用规则判断，后续可结合 evaluation harness 做阈值校准。
- alias 词表目前通过 JSON 文件加载，后续可扩展 repo / domain 作用域。

## 新增能力

### 1. 工程化 Lexical Retrieval

新增 `src/agent_context_platform/lexical.py`。

实现内容：

- 支持英文关键词、中文片段、camelCase、PascalCase、snake_case、路径、表名、字段名和 symbol token。
- 支持领域词 / 工程词优先、`jieba` search mode 中文分词，以及无分词器时的规则 fallback。
- 对 `title`、`summary`、`content`、`metadata`、`source.symbol`、`source.table`、`source.column`、`source.heading_path`、`source.path` 做字段加权。
- 使用 BM25-like scoring 输出 lexical 分数、命中 token 和命中字段。

价值：

- 相比原来的简单 SQL LIKE，工程 token 的召回和解释性更稳定。
- 中文业务问题可以更容易命中英文类名、表名和文档章节。

### 2. 领域词 Alias Expansion

新增 `src/agent_context_platform/aliases.py`，并在 `runtime.py` 中增加可选配置 `ACP_ALIAS_FILE`。

示例配置：

```json
{
  "aliases": [
    {
      "term": "现金流审批",
      "expands_to": [
        "cashflow approval",
        "PaymentApprovalService",
        "payment_approval"
      ]
    }
  ]
}
```

实现内容：

- query 命中业务术语后扩展为代码 / 文档 / 表结构中更常见的工程表达。
- alias expansion 进入检索 tokenization。
- alias 命中记录到内部 retrieval trace，便于后续调试。
- 配置格式错误会在应用启动时给出明确错误。

价值：

- 解决“用户用中文业务词提问，但代码和文档里是英文工程命名”的召回断层。

### 3. 多路召回与 RRF 融合

更新 `src/agent_context_platform/retrieval.py`，新增 `src/agent_context_platform/retrieval_trace.py`。

实现内容：

- `lexical`：基于 BM25-like scoring 的关键词 / 工程 token 召回。
- `vector`：复用现有 embedding / pgvector 检索路径。
- `symbol`：读取开发者 B 已实现的 symbol catalog，支持 exact / prefix / lightweight fuzzy recall。
- 使用 RRF 融合多路候选，避免直接混合异构原始分数。
- 候选去重身份使用 `(repo, item_id)`，兼容 multi repo 共库隔离。
- `SearchResult.score_parts` 返回 `keyword`、`lexical`、`vector`、`symbol`、`rrf`。
- `match_reason` 展示命中通道和命中原因。

价值：

- 代码类名 / 方法名 / 表名这类强结构化信号不再只依赖正文 keyword。
- keyword-only、vector-only、symbol-only 候选都可以进入同一个排序框架。
- 后续评测时可以按通道分析召回质量。

### 4. Context Composer 与 Token Budget

新增 `src/agent_context_platform/context_composer.py`，并更新 `src/agent_context_platform/context_builder.py`。

实现内容：

- `TaskContextBuilder` 继续负责 code、db schema、docs、similar implementations 四类检索编排。
- `ContextComposer` 负责结果裁剪、missing context、risks 和 citations 汇总。
- `build-task-context` 支持 `constraints.token_budget`。
- 当 token budget 导致某类上下文为空时，会继续通过 `missing_context` 和 `risks` 暴露。
- citations 汇总去重，保证返回结果都可追溯。

价值：

- Agent 不会无控制地接收过大的上下文包。
- 上下文不足不会被包装成确定结论，调用方可以明确看到缺口。

## 代码影响范围

| 文件 | 影响 |
|---|---|
| `src/agent_context_platform/retrieval.py` | 从固定 keyword/vector 加权升级为 lexical/vector/symbol 多路召回和 RRF 融合 |
| `src/agent_context_platform/lexical.py` | 新增工程 tokenization 和 lexical scoring |
| `src/agent_context_platform/aliases.py` | 新增领域词 alias expansion |
| `src/agent_context_platform/retrieval_trace.py` | 新增内部 retrieval trace 结构 |
| `src/agent_context_platform/context_composer.py` | 新增上下文组装、token budget 和 sufficiency rule |
| `src/agent_context_platform/context_builder.py` | 接入 Context Composer |
| `src/agent_context_platform/runtime.py` | 增加可选 `ACP_ALIAS_FILE` 配置 |
| `docs/api/context-api.md` | 补充 `score_parts` 和 `token_budget` 说明 |
| `docs/architecture/design.md` | 补充多路召回、RRF、alias 和 composer 说明 |

## 验证情况

已新增和更新测试：

- `tests/test_lexical.py`
- `tests/test_retrieval.py`
- `tests/test_context_api.py`
- `tests/test_runtime.py`

本地验证结果：

```text
uv run pytest
112 passed
```

## 后续建议

下一步不建议继续扩大代码改动范围，优先做两件事：

1. 准备 10 到 20 条真实研发任务样例，用 evaluation harness 对比改动前后的召回证据。
2. 基于评测结果调 BM25 字段权重、alias 词表、RRF 参数和 sufficiency 阈值。
