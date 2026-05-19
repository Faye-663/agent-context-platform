# 阶段五实际验证记录

## 当前覆盖范围

阶段五用于补齐真实项目可用前的收口项。任务 12 当前覆盖：

- DashScope native `EmbeddingProvider` 调用。
- Java、SQL、Markdown 三类离线索引结果的批量 embedding 写入。
- `item_embeddings` 按 provider、model、dimension 存储多模型 embedding。
- 应用层写入维度校验与 PostgreSQL 动态维度约束。
- 查询侧在未显式传 `query_embedding` 时自动生成 query embedding。
- provider 调用失败时返回 `embedding_unavailable`，不静默降级。

## 已执行验证

### 单元与回归验证

```text
uv run --extra test pytest
44 passed
```

```text
uv run --extra test python scripts/run_mvp_evaluation.py
sample_count=10
passed=true
top5_hit_rate=1.0
top10_irrelevant_result_count=0
source_citation_completeness=1.0
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

`.env` 必须包含完整 DashScope 配置，并补齐：

```powershell
$env:ACP_EMBEDDING_BATCH_SIZE = "10"
```

如果使用本地隔离 PostgreSQL / pgvector：

```powershell
$toolRoot = "D:\Code\ACPTools"
$env:PIXI_HOME = Join-Path $toolRoot "pixi-home"
$env:PIXI_CACHE_DIR = Join-Path $toolRoot "pixi-cache"
$env:ACP_DATABASE_URL = "postgresql+psycopg://postgres@localhost:55432/agent_context_platform"

& "$toolRoot\pixi.exe" run --manifest-path "$toolRoot\pg-pixi\pixi.toml" pg_ctl -D "$toolRoot\pg-data" -l "$toolRoot\postgres.log" -o "-p 55432" start
uv run alembic upgrade head
uv run --extra test python scripts/verify_task12_embeddings.py --env-file D:\Code\GitHub\agent-context-platform\.env
```

## 未覆盖边界

- 任务 13 的数据库侧 pgvector 相似度排序尚未实现。
- 真实脱敏 Java 项目索引库召回评测仍属于任务 14。
