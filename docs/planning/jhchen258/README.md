# jhchen258 本地首次运行与验证说明

本文记录在个人分支上验证 `agent-context-platform` 的推荐流程。目标是让新同事能按同一套步骤完成：

- 初始化 Python 依赖。
- 配置 PostgreSQL / pgvector 数据库。
- 索引真实工程目录。
- 写入 OpenAI-compatible embedding。
- 启动 Context API 并验证查询结果。

本文不提交真实 API key、数据库密码或内部网关地址。真实值只写入本机 `.env` 或当前 shell 环境变量。

## 1. 前置条件

Windows 11 本地建议准备：

- `uv`
- PostgreSQL
- `pgvector` extension
- 可访问的 OpenAI-compatible embedding 服务
- 待索引工程目录，例如：

```text
D:\repo\TMC\stlm\tmc-settlement
```

本项目的 Python 版本由 `pyproject.toml` 和 `uv.lock` 管理，通常不需要手动安装项目依赖。

## 2. 安装依赖

在 `agent-context-platform` 仓库根目录执行：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv sync --extra test
```

验证依赖安装：

```powershell
uv run pytest
```

期望结果是单元测试通过；live regression 如果没有启动 Context API，可能会被 skip。

## 3. 准备本地配置

复制配置样例：

```powershell
Copy-Item .env.example .env
```

按本机环境修改 `.env`。示例：

```dotenv
ACP_DATABASE_URL=postgresql+psycopg://postgres:<local-password>@127.0.0.1:5432/agent_context_platform

ACP_ENV=local
ACP_LOG_LEVEL=INFO
ACP_SQL_ECHO=false

ACP_CONTEXT_API_BASE_URL=http://127.0.0.1:8000

ACP_EMBEDDING_PROVIDER=openai
ACP_EMBEDDING_BASE_URL=<openai-compatible-embedding-gateway>/v1
ACP_EMBEDDING_API_KEY=<local-api-key>
ACP_EMBEDDING_MODEL=Qwen3-Embedding-4B
ACP_EMBEDDING_DIMENSION=1024
ACP_EMBEDDING_BATCH_SIZE=10

ACP_DEFAULT_REPO=tmc-settlement
```

注意：

- `ACP_DEFAULT_REPO` 必须和后续 `acp-index --repo` 一致。
- `ACP_EMBEDDING_API_KEY` 不要提交到 Git。
- 如果本机数据库密码不同，只改本机 `.env`。

## 4. 加载配置并初始化数据库

PowerShell 中先把 `.env` 加载到当前进程：

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -and -not $_.TrimStart().StartsWith("#") -and $_.Contains("=")) {
        $name, $value = $_.Split("=", 2)
        Set-Item -Path "Env:$($name.Trim())" -Value $value.Trim().Trim('"')
    }
}
```

执行数据库迁移：

```powershell
uv run alembic upgrade head
```

## 5. 先 dry-run 检查索引范围

对 `tmc-settlement` 工程做 dry-run：

```powershell
uv run acp-index `
  --root "D:\repo\TMC\stlm\tmc-settlement" `
  --repo "tmc-settlement" `
  --dry-run
```

检查输出中的关键字段：

- `files_scanned`
- `files_indexed`
- `items_estimated`
- `symbols_estimated`
- `failures`

如果 `failures` 为空，再执行真实写库。

## 6. 写入索引和 embedding

推荐使用环境变量中的数据库和 embedding 配置：

```powershell
uv run acp-index `
  --root "D:\repo\TMC\stlm\tmc-settlement" `
  --repo "tmc-settlement" `
  --with-embedding
```

这条命令含义：

- `--root`：本机真实工程目录。
- `--repo`：写入索引库的稳定 repo identity。
- `--with-embedding`：除写入结构化索引外，也调用 embedding provider 写入向量。

如果不想依赖 `.env` 是否已加载，也可以把配置显式放到 CLI 参数里：

```powershell
uv run acp-index `
  --root "D:\repo\TMC\stlm\tmc-settlement" `
  --repo "tmc-settlement" `
  --database-url "$env:ACP_DATABASE_URL" `
  --with-embedding `
  --embedding-base-url "$env:ACP_EMBEDDING_BASE_URL" `
  --embedding-api-key "$env:ACP_EMBEDDING_API_KEY" `
  --embedding-model "$env:ACP_EMBEDDING_MODEL" `
  --embedding-dimension "$env:ACP_EMBEDDING_DIMENSION" `
  --embedding-batch-size "$env:ACP_EMBEDDING_BATCH_SIZE"
```

完成后检查输出：

- `items_written` 大于 0。
- `symbols_written` 大于 0。
- `embedding_written` 大于 0。
- `failures` 为空。
- `repo` 等于 `tmc-settlement`。

## 7. 启动 Context API

```powershell
uv run uvicorn agent_context_platform.asgi:app --host 127.0.0.1 --port 8000 --env-file .env
```

打开：

```text
http://127.0.0.1:8000/docs
```

## 8. 验证查询

在 Swagger 中优先验证：

- `POST /search-code`
- `POST /search-db-schema`
- `POST /search-doc`
- `POST /build-task-context`

示例请求：

```json
{
  "query": "结算流程涉及哪些核心类和表",
  "limit": 5,
  "filters": {
    "repo": "tmc-settlement"
  },
  "debug_options": {
    "include_trace": true
  }
}
```

`build-task-context` 示例：

```json
{
  "task": "我要修改 tmc-settlement 的结算校验逻辑，请返回相关代码、表结构、文档和待确认项。",
  "limits": {
    "code": 5,
    "db_schema": 5,
    "doc": 5,
    "similar_implementations": 5
  },
  "constraints": {
    "repo": "tmc-settlement",
    "token_budget": 6000
  },
  "debug_options": {
    "include_trace": true
  }
}
```

验证重点：

- 返回结果里的 `source.repo` 应为 `tmc-settlement`。
- 返回结果应包含 `source.path`、行号或 symbol 等引用信息。
- `_trace` 能看到各检索通道的基础信息。
- `missing_context` 为空或能明确说明缺了哪类上下文。

## 9. 常见问题

### `acp-index` 没读到 `.env`

`acp-index` 不会自动读取 `.env`。需要先执行第 4 步的 PowerShell 加载命令，或使用第 6 步的 CLI 参数方式。

### `embedding_written` 为 0

通常是以下原因：

- 没有传 `--with-embedding`。
- embedding 配置不完整。
- provider 返回维度和 `ACP_EMBEDDING_DIMENSION` 不一致。
- 待索引文件没有变化，增量索引跳过了写入。

### 查询结果为空

优先检查：

- `ACP_DEFAULT_REPO` 是否等于 `tmc-settlement`。
- 请求里的 `filters.repo` 或 `constraints.repo` 是否等于 `tmc-settlement`。
- 索引命令是否使用了 `--repo "tmc-settlement"`。
- 数据库连接是否和 Context API 使用的是同一个 `ACP_DATABASE_URL`。

