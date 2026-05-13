# 阶段三实际验证记录

## 验证范围

- 混合检索支持按 `asset_type`、`language`、`symbol_type`、`table`、`path_prefix` 过滤。
- 混合检索会组合关键词分数和 embedding 余弦相似度，并返回 `score`、`score_parts`、`match_reason`。
- `search-code`、`search-db-schema`、`search-doc` 三个 FastAPI 接口返回 `SearchResult` 契约结构。
- 参数错误返回 `invalid_request`。
- 查询日志包含 request id、接口名称、返回数量和耗时。
- `build-task-context` 能聚合代码、表结构、文档和相似实现，并在上下文缺失时返回 `missing_context` 和 `risks`。

## 已执行验证

```powershell
uv run --extra test pytest
```

结果：

```text
19 passed
```

## 当前边界

- 当前自动化验证使用 SQLite repository 和测试样本，不依赖本机 PostgreSQL。
- embedding 分数通过已落库的测试向量计算，尚未验证 PostgreSQL + pgvector 数据库侧排序性能。
- 首版接口使用应用内 `HybridSearchService` 注入，后续 MCP 包装层应继续只调用 HTTP 接口，不复制检索逻辑。
