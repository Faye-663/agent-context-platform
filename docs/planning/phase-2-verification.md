# 阶段二实际验证记录

## 验证结论

阶段二离线索引器当前有两类验证入口：

1. 纯 `pytest` 单元测试，使用进程内 SQLite，适合快速回归。
2. `scripts/verify_phase2_e2e_sqlite.py`，使用 `.local/phase2-e2e` 下的正式 Java、SQL、Markdown 样本文件，并写入可持久化 SQLite 文件，适合人工查看和端到端核对。

本次验证结论：通过。

## 验证范围

已覆盖：

- Java 文件索引：class、method、annotation、signature、file path、line range。
- SQL DDL 索引：table、column、index、DDL 来源。
- Markdown 文档索引：heading path、正文片段、file path、line range。
- `IndexedItem` 与 `SourceCitation` 模型校验。
- 离线索引结果写入 repository，并按资产类型读回。

未覆盖：

- embedding 生成与向量维度校验。
- MCP 包装层。

阶段三已补充真实 PostgreSQL + pgvector 写读验证、Hybrid Search、Context API 和 `build-task-context` 运行时验证。embedding provider 与 MCP 包装层在后续阶段验证。

## 验证命令

### 纯 pytest 进程内验证

该路径只验证 indexer 和 repository 行为，SQLite 使用 `sqlite:///:memory:`，测试结束后不会留下数据库文件。

```powershell
$env:UV_CACHE_DIR = "D:\Code\GitHub\agent-context-platform\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "D:\Code\GitHub\agent-context-platform\.uv-python"
$env:UV_PROJECT_ENVIRONMENT = "D:\Code\GitHub\agent-context-platform\.venv"
uv run --extra test pytest .\tests\test_indexers.py
```

### 持久化 SQLite 验证

该路径使用 `.local/phase2-e2e` 下的正式样本文件：

- `.local/phase2-e2e/src/main/java/example/PaymentMessageBuilder.java`
- `.local/phase2-e2e/schema/payment.sql`
- `.local/phase2-e2e/docs/payment.md`

脚本会写入 `.local/phase2-e2e/indexed-items.sqlite`，可通过 IDE SQLite 数据源或 SQLite 客户端查看。

```powershell
$env:UV_CACHE_DIR = "D:\Code\GitHub\agent-context-platform\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "D:\Code\GitHub\agent-context-platform\.uv-python"
$env:UV_PROJECT_ENVIRONMENT = "D:\Code\GitHub\agent-context-platform\.venv"
uv run python .\scripts\verify_phase2_e2e_sqlite.py
```

脚本动作如下：

1. 检查 `.local/phase2-e2e` 下 Java、SQL、Markdown 样本文件是否存在。
2. 从磁盘读取样本内容。
3. 调用 `index_java_source`、`index_sql_ddl`、`index_markdown_document`。
4. 使用 SQLite 创建 `indexed_items` 表。
5. 清空索引相关表，避免历史本地数据影响验证计数。
6. 调用 `IndexedItemRepository.save()` 写入全部索引结果。
7. 保留 SQLite 文件本身，便于 IDE 或 SQLite 客户端查看。
8. 重新查询 `code`、`db_schema`、`doc` 三类结果并断言关键字段。

## 验证输出

纯 pytest 进程内验证输出：

```text
4 passed
```

持久化 SQLite 验证输出：

```json
{
  "status": "PASS",
  "sample_root": "D:\\Code\\GitHub\\agent-context-platform\\.local\\phase2-e2e",
  "sqlite_db": "D:\\Code\\GitHub\\agent-context-platform\\.local\\phase2-e2e\\indexed-items.sqlite",
  "indexed_total": 9,
  "persisted_counts": {
    "code": 2,
    "db_schema": 4,
    "doc": 3
  },
  "method_source": {
    "source_type": "code",
    "repo": "phase2-e2e",
    "path": "src/main/java/example/PaymentMessageBuilder.java",
    "start_line": 5,
    "end_line": 8,
    "symbol": "PaymentMessageBuilder.build",
    "table": null,
    "column": null,
    "heading_path": null
  },
  "table_metadata": {
    "symbol_type": "table",
    "table": "payment_order",
    "columns": [
      "id",
      "status",
      "amount"
    ],
    "indexes": [
      "idx_payment_order_status"
    ]
  },
  "doc_source": {
    "source_type": "doc",
    "repo": "phase2-e2e",
    "path": "docs/payment.md",
    "start_line": 5,
    "end_line": 7,
    "symbol": null,
    "table": null,
    "column": null,
    "heading_path": "Payment Integration > Message Generation"
  }
}
```

## 后续验证要求

后续阶段需要补充：

- embedding provider 配置确认后，补充 embedding 维度与 pgvector 字段兼容性验证。
- MCP 包装层到 Context API 的调用验证。
- 固定评测集上的召回质量验证。
