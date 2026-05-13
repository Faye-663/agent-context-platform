# 阶段二实际验证记录

## 验证结论

阶段二离线索引器已完成一次实际落盘验证。验证不是只运行单元测试，而是使用真实文件路径写入 Java、SQL、Markdown 三类样本，从磁盘读取内容后执行索引，随后写入现有 `IndexedItemRepository` 并重新读回断言。

本次验证结论：通过。

## 验证范围

已覆盖：

- Java 文件索引：class、method、annotation、signature、file path、line range。
- SQL DDL 索引：table、column、index、DDL 来源。
- Markdown 文档索引：heading path、正文片段、file path、line range。
- `IndexedItem` 与 `SourceCitation` 模型校验。
- 离线索引结果写入 repository，并按资产类型读回。

未覆盖：

- 真实 PostgreSQL + pgvector 的阶段二索引写入链路。
- embedding 生成与向量维度校验。
- Hybrid Search、Context API、`build-task-context` 和 MCP 包装层。

未覆盖原因：阶段二当前只实现离线索引器，尚未实现 embedding provider、向量检索和 HTTP / MCP 入口。真实 PostgreSQL + pgvector 写入验证应在进入阶段三检索前补充，避免把 SQLite repository 验证误判为完整数据库链路验证。

## 验证命令

单元测试：

```powershell
$env:UV_CACHE_DIR = "D:\Code\GitHub\agent-context-platform-phase-2\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "D:\Code\GitHub\agent-context-platform-phase-2\.uv-python"
uv run --extra test pytest -q
```

实际落盘验证使用一次性 Python 脚本执行，脚本动作如下：

1. 在 `.local/phase2-e2e` 下写入脱敏 Java、SQL、Markdown 样本文件。
2. 从磁盘读取样本内容。
3. 调用 `index_java_source`、`index_sql_ddl`、`index_markdown_document`。
4. 使用 SQLite 创建 `indexed_items` 表。
5. 调用 `IndexedItemRepository.save()` 写入全部索引结果。
6. 重新查询 `code`、`db_schema`、`doc` 三类结果并断言关键字段。

## 验证输出

单元测试输出：

```text
11 passed
```

实际落盘验证输出：

```json
{
  "status": "PASS",
  "sample_root": "D:\\Code\\GitHub\\agent-context-platform-phase-2\\.local\\phase2-e2e",
  "sqlite_db": "D:\\Code\\GitHub\\agent-context-platform-phase-2\\.local\\phase2-e2e\\indexed-items.sqlite",
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

进入阶段三前，需要补充：

- 使用真实 PostgreSQL + pgvector 的离线索引写入验证。
- embedding provider 配置确认后，补充 embedding 维度与 pgvector 字段兼容性验证。
- 固定样本上的关键词检索、结构化过滤和空结果诊断验证。
