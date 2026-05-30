# 阶段五实际验证记录

## 当前覆盖范围

阶段五用于补齐真实项目可用前的收口项。任务 12 当前覆盖：

- DashScope native `EmbeddingProvider` 调用。
- Java、SQL、Markdown 三类离线索引结果的批量 embedding 写入。
- `item_embeddings` 按 provider、model、dimension 存储多模型 embedding。
- 应用层写入维度校验与 PostgreSQL 动态维度约束。
- 查询侧在未显式传 `query_embedding` 时自动生成 query embedding。
- provider 调用失败时返回 `embedding_unavailable`，不静默降级。

任务 13 当前覆盖：

- provider/model/dimension 明确时，repository 层使用 PostgreSQL / pgvector 执行 query embedding 相似度排序。
- `HybridSearchService` 采用有界合并：向量候选由数据库侧按 `<=>` 排序并 `LIMIT`，关键词候选保留数据库阶段过滤与 `LIMIT`，最终仍输出统一 `SearchResult`。
- SQLite 测试路径保留应用侧余弦相似度替代实现，不阻塞单元测试。
- 查询侧继续校验 query embedding 维度，避免不同 embedding model 维度混用。

## 已执行验证

### 单元与回归验证

```text
uv run --extra test pytest
48 passed
```

```text
uv run --extra test python scripts/run_mvp_evaluation.py
sample_count=10
passed=true
top5_hit_rate=1.0
top10_irrelevant_result_count=0
source_citation_completeness=1.0
```

### PostgreSQL / pgvector 相似度排序验证

使用 scratch 数据库 `agent_context_platform_task13` 执行：

```powershell
$env:ACP_DATABASE_URL = "postgresql+psycopg://postgres@localhost:55432/agent_context_platform_task13"
uv run alembic upgrade head
uv run --extra test python scripts/verify_task13_pgvector_search.py
```

迁移输出：

```text
Running upgrade  -> 202605120001
Running upgrade 202605120001 -> 202605190001
```

验证输出：

```text
task13 pgvector search verification passed
top_result=task13:code:vector-top
vector_score=1.0
operator=<=>
limit_applied=true
```

### PostgreSQL / pgvector 迁移验证

使用 scratch 数据库 `agent_context_platform_task12` 执行：

```text
uv run alembic upgrade head
Running upgrade  -> 202605120001
Running upgrade 202605120001 -> 202605190001
```

迁移后确认：

```text
item_embeddings.dimension = int4
item_embeddings.embedding = vector
ck_item_embeddings_vector_matches_dimension exists
indexed_items.embedding removed
```

### DashScope 真实 embedding 验证

使用主仓库 `.env` 中的 DashScope key，并在当前进程覆盖：

```powershell
$env:ACP_DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:55432/agent_context_platform_task12"
$env:ACP_EMBEDDING_BATCH_SIZE = "10"
uv run --extra test python scripts/verify_task12_embeddings.py --env-file D:\Code\GitHub\agent-context-platform\.env
```

输出：

```text
task12 embedding verification passed
model=tongyi-embedding-vision-flash-2026-03-06
dimension=768
batch_size=10
saved_count=3
embedding_counts=code:1,db_schema:1,doc:1
top_code_result=code:src/main/java/example/Task12PaymentService.java:Task12PaymentService,vector=0.8746939897537231
```

## 真实验证命令

基础命令默认在 Windows / PowerShell 中执行。先固定本仓库本地依赖缓存：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
```

如果使用本地隔离 PostgreSQL / pgvector：

```powershell
$toolRoot = "D:\Code\ACPTools"
$env:PIXI_HOME = Join-Path $toolRoot "pixi-home"
$env:PIXI_CACHE_DIR = Join-Path $toolRoot "pixi-cache"

& "$toolRoot\pixi.exe" run --manifest-path "$toolRoot\pg-pixi\pixi.toml" pg_ctl -D "$toolRoot\pg-data" -l "$toolRoot\postgres.log" -o "-p 55432" start
```

任务 12 需要 `.env` 包含完整 DashScope 配置：

```powershell
$env:ACP_DATABASE_URL = "postgresql+psycopg://postgres@localhost:55432/agent_context_platform"
uv run alembic upgrade head
uv run --extra test python scripts/verify_task12_embeddings.py --env-file D:\Code\GitHub\agent-context-platform\.env
```

任务 13 不依赖外部 embedding provider，可使用独立 scratch 数据库验证 pgvector 排序：

```powershell
$env:ACP_DATABASE_URL = "postgresql+psycopg://postgres@localhost:55432/agent_context_platform_task13"
uv run alembic upgrade head
uv run --extra test python scripts/verify_task13_pgvector_search.py
```

验证完成后停止本地数据库：

```powershell
& "$toolRoot\pg-pixi\.pixi\envs\default\Library\bin\pg_ctl.exe" -D "$toolRoot\pg-data" stop
```

## 未覆盖边界

- 真实项目初始化索引 CLI P0 仍属于任务 14。
- 真实脱敏 Java 项目索引库召回评测仍属于任务 15。
