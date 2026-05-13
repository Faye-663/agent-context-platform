# 阶段四实际验证记录

## 验证范围

- MCP 包装层使用 MCP Python SDK `FastMCP` 暴露工具。
- MCP 工具入参与 Context API 请求模型保持一致。
- MCP 包装层只通过 HTTP client 调用 Context API，不直接访问 repository、SQLAlchemy session 或数据库。
- Context API 错误会转换成 Agent 可读的 `ContextApiError`，保留错误码和 message。
- 固定评测集包含 10 个脱敏半真实工程任务样本，每个样本包含任务描述、期望命中来源、无关结果判定规则。
- 回归脚本可以重复运行，并输出 Top5 命中率、Top10 明显无关结果数量、来源引用完整率和失败样本详情。

## 已执行验证

新增 MCP 包装层测试：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test pytest tests/test_mcp_server.py
```

结果：

```text
4 passed
```

覆盖点：

- `ContextApiToolClient.build_task_context()` 会按 `/build-task-context` HTTP 契约发起请求。
- `ContextApiError` 会保留 Context API 返回的错误码和 message。
- 非 JSON 错误响应会转换成 `context_api_error`。
- `FastMCP.list_tools()` 能看到 `search_code`、`search_db_schema`、`search_doc`、`build_task_context`。
- `FastMCP.call_tool("build_task_context", ...)` 能实际触发 Context API client 调用。

新增评测计算测试：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test pytest tests/test_evaluation.py
```

结果：

```text
2 passed
```

固定评测集回归脚本：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test python scripts/run_mvp_evaluation.py
```

结果：

```text
sample_count=10
passed=true
top5_hit_rate=1.0
top10_irrelevant_result_count=0
source_citation_completeness=1.0
failed_sample_ids=[]
```

完整测试：

```powershell
$env:UV_CACHE_DIR = ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = ".uv-python"
uv run --extra test pytest
```

结果：

```text
26 passed
```

## 当前边界

- MCP server 默认调用 `http://127.0.0.1:8000`，但仓库仍未提供固定 ASGI 部署入口；长期运行服务仍需先补应用装配层。
- 阶段四评测脚本使用脚本内脱敏样本语料写入 SQLite repository，再通过 FastAPI `TestClient` 调用 `/build-task-context`，用于稳定回归。
- 当前评测尚未接入真实脱敏 Java 项目索引库，也未覆盖外部 EmbeddingProvider 和数据库侧 pgvector 相似度排序。
- `irrelevant_rules` 已进入样本文件；自动统计明显无关结果时使用可重复计算的 `irrelevant_result_ids`。
