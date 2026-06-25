# Playground MCP 人工验收

本验收不引入浏览器自动化依赖。启动 Context API 与 remote MCP 后，在浏览器打开 `playground/index.html`，连接 `http://127.0.0.1:8001/mcp`。

1. 调用 `tools/list`，确认四个 tool 可见。
2. 调用 `search_code`，勾选 trace，确认原始页同时展示 JSON-RPC request 和 response，trace 页展示 token、alias、channel rank 与 RRF。
3. 使用包含 `<img src=x onerror=alert(1)>` 的 query 或 mock response，确认页面只显示文本，不执行脚本。
4. 调用无命中 query，确认 `result_status=empty` 可见且不被当作错误。

启动命令和 streamable HTTP 环境变量见 README 的 remote MCP HTTP 小节。验收记录需保存请求、response、浏览器版本和结论，不把含敏感信息的 payload 提交到仓库。

## 2026-06-25 MCP wire 验证记录

本次只验证 remote MCP server 的 JSON-RPC wire 和 tool handler，不替代浏览器 Playground UI / XSS 验收。

- Context API：`http://127.0.0.1:8011`
- Remote MCP：`http://127.0.0.1:8012/mcp`
- repo：`github.com/BaSui01/smart-campus`
- expected commit：`95c69bb5dcfe943d32ab3a7e6947a29aeb140ae7`
- embedding：未启用；未发起真实 embedding 请求

验证结果：

- `initialize` 成功返回 session id。
- `tools/list` 成功返回 `search_code`、`search_db_schema`、`search_doc`、`build_task_context`。
- `tools/call search_doc` 成功返回 `result_status=ok`、`result_count=2`，结果 repo 与 commit 均匹配上述验收范围。
- `tools/call search_code` 使用 query `AiChatController`、`limit=3` 成功返回 `result_status=ok`、`result_count=3`，结果 repo 与 commit 均匹配上述验收范围；首条结果为 `code:backend/smart-campus-ai/src/main/java/com/smartcampus/ai/controller/AiChatController.java:AiChatController`。

已知缺口：

- 尚未在真实浏览器打开 `playground/index.html` 完成 UI 展示与 XSS 安全文本渲染验收。
- Python MCP SDK `streamablehttp_client` 在 `initialize` 前收到 502，未进入 ACP tool handler；手工 JSON-RPC wire 可用，先按 SDK/client 兼容性问题单独跟踪。
