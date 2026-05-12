# Context API 契约

## 设计目标

Context API 是系统稳定内核。MCP wrapper、CLI 或未来 UI 都应调用同一组 API，避免不同入口产生行为差异。

首版 API 面向 Agent Tool Calling，不面向泛问答。

## 公共模型

以下模型是文档级契约，不绑定具体编程语言。后续实现应保持字段语义稳定。

### IndexedItem

统一表示可检索工程资产。

| 字段 | 说明 |
|---|---|
| `id` | 索引项唯一 ID |
| `asset_type` | `code`、`db_schema`、`doc` |
| `title` | 面向结果展示的标题，例如 class 名、表名、文档标题 |
| `content` | 可检索正文或摘要 |
| `summary` | 面向 Agent 的短摘要 |
| `metadata` | 结构化元数据，例如 language、symbol_type、table_name |
| `source` | `SourceCitation` |

### SourceCitation

统一表示来源引用。

| 字段 | 说明 |
|---|---|
| `source_type` | `code`、`db_schema`、`doc` |
| `repo` | 来源仓库标识；单仓 MVP 可以为空或固定 |
| `path` | 来源文件路径 |
| `start_line` | 起始行号；无法定位时为空 |
| `end_line` | 结束行号；无法定位时为空 |
| `symbol` | 代码符号，例如 class 或 method |
| `table` | 表名 |
| `column` | 字段名 |
| `heading_path` | Markdown 标题路径 |

约束：

- 代码结果必须包含 `path` 和行号。
- SQL 表级结果必须包含 `table`。
- SQL 字段级结果必须包含 `table` 和 `column`。
- Markdown 结果必须包含 `path` 和 `heading_path`。

### SearchResult

统一表示检索结果。

| 字段 | 说明 |
|---|---|
| `item` | `IndexedItem` |
| `score` | 统一排序分数 |
| `score_parts` | 可选，关键词、向量、过滤加权等分数来源 |
| `match_reason` | 命中原因，便于 Agent 判断可用性 |
| `source` | `SourceCitation` |

### TaskContext

`build-task-context` 的返回上下文包。

| 字段 | 说明 |
|---|---|
| `query` | 原始任务描述 |
| `related_code` | 相关代码结果 |
| `related_db_schema` | 相关表结构结果 |
| `related_docs` | 相关文档结果 |
| `similar_implementations` | 推荐参考实现 |
| `risks` | 风险提示，例如缺少表结构或文档过期风险 |
| `missing_context` | 明确缺失的上下文类型 |
| `citations` | 本次上下文包使用到的来源引用汇总 |

## API 列表

### search-code

搜索 Java 代码结构和相似实现。

请求：

```json
{
  "query": "payment message generator",
  "limit": 10,
  "filters": {
    "language": "java",
    "symbol_type": ["class", "method"],
    "path_prefix": "src/main/java"
  }
}
```

响应：

```json
{
  "results": [
    {
      "item": {
        "id": "code:example:PaymentMessageBuilder",
        "asset_type": "code",
        "title": "PaymentMessageBuilder.build",
        "summary": "构造支付报文的示例方法。",
        "metadata": {
          "language": "java",
          "symbol_type": "method",
          "signature": "build(PaymentRequest request)"
        },
        "source": {
          "source_type": "code",
          "path": "src/main/java/example/PaymentMessageBuilder.java",
          "start_line": 32,
          "end_line": 88,
          "symbol": "PaymentMessageBuilder.build"
        }
      },
      "score": 0.82,
      "match_reason": "方法名和正文同时命中 payment/message/build"
    }
  ]
}
```

### search-db-schema

搜索 SQL 表结构。

请求：

```json
{
  "query": "payment order status",
  "limit": 10,
  "filters": {
    "table": null
  }
}
```

响应必须返回表级或字段级来源引用。

### search-doc

搜索 Markdown 文档。

请求：

```json
{
  "query": "payment integration design",
  "limit": 10,
  "filters": {
    "path_prefix": "docs"
  }
}
```

响应必须返回 `path`、`heading_path` 和可定位行号。

### build-task-context

构建任务上下文包，是 MVP 首个验收工作流。

请求：

```json
{
  "task": "新增某地区支付接口，复用已有支付报文生成能力",
  "limits": {
    "code": 8,
    "db_schema": 5,
    "docs": 5,
    "similar_implementations": 5
  },
  "constraints": {
    "language": "java",
    "include_tests": true
  }
}
```

响应：

```json
{
  "query": "新增某地区支付接口，复用已有支付报文生成能力",
  "related_code": [],
  "related_db_schema": [],
  "related_docs": [],
  "similar_implementations": [],
  "risks": [
    "未召回到明确的错误码映射文档，需要人工确认。"
  ],
  "missing_context": [
    "error-code-doc"
  ],
  "citations": []
}
```

约束：

- 不允许返回没有来源的上下文。
- 不允许把缺失上下文包装成确定结论。
- 当某类结果为空时，必须在 `missing_context` 或 `risks` 中体现。

## 错误处理

首版 API 至少区分：

| 错误 | 触发条件 |
|---|---|
| `invalid_request` | 缺少 `query`、`task` 或参数格式错误 |
| `index_not_ready` | 索引尚未构建或不可用 |
| `embedding_unavailable` | embedding provider 不可用 |
| `storage_unavailable` | PostgreSQL 或 pgvector 查询失败 |

错误响应必须包含：

- 错误码。
- 面向运维定位的 message。
- 可选 request id。

## 日志要求

每次查询应记录：

- request id。
- API name。
- 查询文本长度，不记录敏感全文日志作为默认行为。
- filters。
- 各资产类型返回数量。
- 查询耗时。
- 错误码。

日志必须便于排查召回为空、结果无关、向量服务失败、数据库失败等问题。
