# 阶段三实际验证记录

## 验证范围

- 混合检索支持按 `asset_type`、`language`、`symbol_type`、`table`、`path_prefix` 过滤。
- 混合检索会组合关键词分数和 embedding 余弦相似度，并返回 `score`、`score_parts`、`match_reason`。
- `search-code`、`search-db-schema`、`search-doc` 三个 FastAPI 接口返回 `SearchResult` 契约结构。
- 参数错误返回 `invalid_request`。
- 查询日志包含 request id、接口名称、返回数量和耗时。
- `build-task-context` 能聚合代码、表结构、文档和相似实现，并在上下文缺失时返回 `missing_context` 和 `risks`。
- 真实 PostgreSQL / pgvector 环境可以执行迁移、写入测试向量并通过 Context API 完成检索。

## 已执行验证

```powershell
uv run --extra test pytest
```

结果：

```text
20 passed
```

真实运行时验证：

```powershell
$env:ACP_DATABASE_URL = "postgresql+psycopg://postgres@localhost:55432/agent_context_platform"
uv run alembic upgrade head
uv run --extra test python scripts/verify_phase3_runtime.py
```

结果：

```text
phase3 runtime verification passed
database_url=postgresql+psycopg://postgres@localhost:55432/agent_context_platform
result_counts=code:1,db_schema:1,doc:1,citations:3
```

## 当前边界

- 当前自动化测试仍使用 SQLite repository 和测试样本，便于快速回归。
- 真实运行时验证使用 PostgreSQL + pgvector 写入测试向量并通过 API 查询。
- embedding 分数通过已落库的测试向量在应用侧计算，尚未接入外部 EmbeddingProvider。
- 尚未实现数据库侧 pgvector 相似度排序。
- 当前 FastAPI 入口是 `create_app(search_service)` 应用工厂，尚未提供固定 ASGI 部署入口。
- 首版接口使用应用内 `HybridSearchService` 注入，后续 MCP 包装层应继续只调用 HTTP 接口，不复制检索逻辑。
