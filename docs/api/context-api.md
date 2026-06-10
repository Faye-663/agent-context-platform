# Context API 契约

## 设计目标

Context API 是系统稳定内核。MCP wrapper、CLI 或未来 UI 都应围绕同一组接口和模型组织，避免不同入口产生行为差异。

当前 API 面向 Coding Agent 的工程上下文检索，不面向泛问答。

## 公共模型

以下模型是文档级契约，对应 `src/agent_context_platform/models.py`。

### IndexedItem

统一表示可检索工程资产。

| 字段 | 说明 |
|---|---|
| `id` | 稳定可重建的索引项唯一 ID |
| `asset_type` | `code`、`db_schema`、`doc` |
| `title` | 面向结果展示的标题 |
| `content` | 参与检索和 embedding 的主体文本 |
| `summary` | 面向 Agent 的短摘要 |
| `metadata` | 结构化元数据，例如 `language`、`symbol_type`、`table` |
| `source` | `SourceCitation` |

约束：`asset_type` 必须与 `source.source_type` 一致。

### SourceCitation

统一表示来源引用。

| 字段 | 说明 |
|---|---|
| `source_type` | `code`、`db_schema`、`doc` |
| `repo` | 来源仓库或语料标识 |
| `branch` | 索引运行时 best-effort 采集的 Git branch，可为空 |
| `commit_sha` | 索引运行时 best-effort 采集的 Git commit SHA，可为空 |
| `file_hash` | 索引时来源文件内容的 SHA-256 指纹，可为空 |
| `indexed_at` | 索引批次时间，使用 UTC ISO 8601 字符串，可为空 |
| `index_batch_id` | 单次 `acp-index` 运行生成的批次 ID，可为空 |
| `path` | 来源文件路径 |
| `start_line` | 起始行号 |
| `end_line` | 结束行号 |
| `symbol` | 代码符号，例如 class 或 method |
| `table` | 表名 |
| `column` | 字段名 |
| `heading_path` | Markdown 标题路径 |

约束：

- code 来源必须包含 `path`、`start_line`、`end_line`。
- db_schema 来源必须包含 `table`。
- doc 来源必须包含 `path`、`heading_path`、`start_line`、`end_line`。
- `end_line` 不能小于 `start_line`。
- `branch`、`commit_sha` 是 best-effort provenance；非 Git 目录、detached HEAD 或 Git 不可用时允许为空。
- `file_hash`、`indexed_at`、`index_batch_id` 由 `acp-index` 写入，用于判断来源新鲜度和索引批次边界。

### SearchResult

统一表示检索结果。

| 字段 | 说明 |
|---|---|
| `item` | `IndexedItem` |
| `score` | 统一排序分数 |
| `score_parts` | 可选，关键词、向量等分数来源 |
| `match_reason` | 命中原因，便于 Agent 判断可用性 |
| `source` | `SourceCitation` |

约束：顶层 `source` 必须与 `item.source` 一致。

### TaskContext

`build-task-context` 的返回上下文包。

| 字段 | 说明 |
|---|---|
| `query` | 原始任务描述 |
| `related_code` | 相关代码结果 |
| `related_db_schema` | 相关表结构结果 |
| `related_docs` | 相关文档结果 |
| `similar_implementations` | 推荐参考实现 |
| `risks` | 风险提示 |
| `missing_context` | 明确缺失的上下文类型 |
| `citations` | 本次上下文包使用到的来源引用汇总 |

约束：`citations` 必须覆盖所有返回结果的来源。

## Search API

### `POST /search-code`

搜索已索引的 Java code。

### `POST /search-db-schema`

搜索已索引的 SQL schema。

### `POST /search-doc`

搜索已索引的 Markdown docs。

三个 endpoint 共用请求体：

```json
{
  "query": "payment message generator",
  "limit": 10,
  "filters": {
    "language": "java",
    "symbol_type": ["class", "method"],
    "path_prefix": "src/main/java",
    "table": null
  },
  "query_embedding": null,
  "request_id": "req-001"
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `query` | 必填，非空自然语言问题或关键词 |
| `limit` | 可选，默认 `10`，范围 `1..50` |
| `filters.language` | 可选，主要用于代码资产 |
| `filters.symbol_type` | 可选，可为字符串或字符串数组 |
| `filters.path_prefix` | 可选，限制仓库子目录 |
| `filters.table` | 可选，用于 DB schema 搜索 |
| `query_embedding` | 可选，用于显式传入 query embedding |
| `request_id` | 可选，用于贯穿日志和调试链路 |

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
          "repo": "example",
          "branch": "main",
          "commit_sha": "abc123",
          "file_hash": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
          "indexed_at": "2026-06-10T08:30:00Z",
          "index_batch_id": "batch-001",
          "path": "src/main/java/example/PaymentMessageBuilder.java",
          "start_line": 32,
          "end_line": 88,
          "symbol": "PaymentMessageBuilder.build"
        }
      },
      "score": 0.82,
      "score_parts": {
        "keyword": 0.7,
        "vector": 0.12
      },
      "match_reason": "方法名和正文同时命中 payment/message/build",
      "source": {
        "source_type": "code",
        "repo": "example",
        "branch": "main",
        "commit_sha": "abc123",
        "file_hash": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        "indexed_at": "2026-06-10T08:30:00Z",
        "index_batch_id": "batch-001",
        "path": "src/main/java/example/PaymentMessageBuilder.java",
        "start_line": 32,
        "end_line": 88,
        "symbol": "PaymentMessageBuilder.build"
      }
    }
  ]
}
```

## Build Task Context API

### `POST /build-task-context`

构建任务上下文包，是 Agent 默认优先入口。

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
    "language": "java"
  },
  "request_id": "req-002"
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `task` | 必填，非空任务描述 |
| `limits` | 可选，按上下文类型控制返回数量 |
| `constraints` | 可选，当前主要用于 `language` 等跨检索约束 |
| `request_id` | 可选，用于日志追踪 |

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
    "db_schema"
  ],
  "citations": []
}
```

约束：

- 不允许返回没有来源的上下文。
- 不允许把缺失上下文包装成确定结论。
- 当某类结果为空时，必须在 `missing_context` 或 `risks` 中体现。

## 错误处理

错误响应使用统一 envelope：

```json
{
  "error": {
    "code": "invalid_request",
    "message": "请求参数格式错误。",
    "details": []
  }
}
```

当前错误码：

| 错误 | 触发条件 |
|---|---|
| `invalid_request` | 缺少必填字段、参数格式错误或业务参数不合法 |
| `embedding_unavailable` | embedding provider、query embedding 或维度校验失败 |
| `storage_unavailable` | PostgreSQL、pgvector 或 SQLAlchemy 查询失败 |

API 当前对上述错误返回 HTTP `400`。调用方应优先读取 `error.code` 和 `error.message`。

## MCP Tool 映射

`acp-mcp-server` 暴露四个 tool：

| MCP tool | Context API |
|---|---|
| `search_code` | `POST /search-code` |
| `search_db_schema` | `POST /search-db-schema` |
| `search_doc` | `POST /search-doc` |
| `build_task_context` | `POST /build-task-context` |

MCP wrapper 会透传 search 请求中的 `query`、`limit`、`filters`、`query_embedding`、`request_id`，以及 build 请求中的 `task`、`limits`、`constraints`、`request_id`。

MCP wrapper 只调用 Context API，不直接访问 repository、SQLAlchemy session 或数据库。

## 日志与调试

Context API 每次查询应记录：

- `request_id`
- API name
- 返回数量
- 查询耗时
- 错误码

默认日志不应记录敏感 task/query 全文。

MCP wrapper 可选写 JSONL 调试日志。开启 `ACP_MCP_LOG_FILE` 后，每次 tool 调用记录：

- `schema_version`
- `timestamp`
- `event=mcp_tool_call`
- `mcp_call_id`
- `tool`
- `request_id`
- `status`
- `elapsed_ms`
- `summary`

默认只写摘要。只有显式设置 `ACP_MCP_LOG_PAYLOADS=true` 时，才写完整 tool arguments 和 tool result payload。

P0 不抓 raw JSON-RPC wire frame，也不依赖 MCP logging notification。stdio MCP 下调试内容必须写入文件或 stderr，不能写 stdout。
