# Phase 1 当前状态与验收缺口

## 验收结论

截至 2026-06-25，Phase 1 的基础实现已合入 `master`，当前 `deng/phase1-smart-campus-acceptance` worktree 分支继续补齐真实项目验收证据与原始需求收尾。本文是 Phase 1 当前实现、验收缺口和下一 session 交接的唯一状态入口。

`P1-T5`（多仓共库隔离）和 `P1-T6`（手动增量索引与一致性清理）已具备实现和自动化测试证据。其余任务多数已具备基础实现，但仍有原始成功标准、公开调试链路或真实项目验证缺口。

这里的未完成项属于已确认的 Phase 1 原始范围，不应以“后续扩大功能范围”处理。其中 `P1-T11` 的同文件重叠片段合并、`P1-T12` 的结果冲突 / stale 最小判断，以及 Python MCP SDK `streamablehttp_client` 502 定位必须在 Phase 1 闭环，不能迁移为后续质量项。

## 当前验证证据

- 2026-06-23 本地执行 `uv run pytest`：`132 passed, 2 skipped`。两个 skipped 均来自 `tests/test_eval_regression.py`：未启动真实 Context API，因而没有连接真实索引库。
- `uv run acp-eval --tasks eval/golden-tasks.json --validate-only` 通过：当前任务集有 4 组、12 条样例。
- `smart-campus` 真实项目语料以显式 repo `github.com/BaSui01/smart-campus`、固定 commit `95c69bb5dcfe943d32ab3a7e6947a29aeb140ae7` 完成 live evaluation：5 组、12 条样例全部通过；初始失败基线见 `docs/evaluation/smart-campus-initial.json`，已修复结果见 `docs/evaluation/smart-campus-final.json`。
- 2026-06-25 按用户要求基于 `ACP_EMBEDDING_PROVIDER=openai` 做静态配置验证，确认当前 `.env` 中的 Jina URL/key/model/dimension/batch 可以被 OpenAI-compatible 配置解析；未构造 provider，未发起真实 embedding 请求。
- 2026-06-25 在不启用 embedding 的临时 Context API / remote MCP 环境下重新执行 `smart-campus` live evaluation，结果见 `docs/evaluation/smart-campus-post-openai-no-embedding.json`：5 组、12 条样例全部通过，`failed_sample_ids=[]`。
- 2026-06-25 手工 JSON-RPC wire 验证 remote MCP：`initialize`、`tools/list`、`search_doc`、`search_code` 均可用，返回结果严格限定在 repo `github.com/BaSui01/smart-campus` 和 commit `95c69bb5dcfe943d32ab3a7e6947a29aeb140ae7`。Python MCP SDK `streamablehttp_client` 仍在 `initialize` 前返回 502，Phase 1 闭环前必须定位并给出可重复验证的结论。
- 本轮验收未启用 embedding；结论仅覆盖 lexical / alias / symbol / RRF 路径，不包含向量召回质量。

## 原始任务完成度

| 任务 | 当前判断 | 已有能力 | 未完成或不符项 |
|---|---|---|---|
| P1-T1 Evaluation Harness | 已完成 | 固定任务格式、指标、`acp-eval`、真实项目 baseline 与 live 评测证据；显式 repo 与 expected commit 已覆盖真实项目验收 | 向量检索未纳入本次验收范围 |
| P1-T2 MCP Tool Contract | 待闭环 | 四个 core tools、`debug_options`、错误 envelope、`result_status=ok/empty`、按检索分组返回完整 trace；2026-06-25 manual JSON-RPC wire 已验证 server/tool handler 可用 | manual wire 不能替代 Python MCP SDK `streamablehttp_client` 验收；当前 SDK client 在 `initialize` 前返回 502，必须定位并修复或形成可重复验证的兼容性结论 |
| P1-T3 MCP Web Playground | 部分完成 | HTTP 调用、完整 MCP wire request/response、可读化结果、trace 和安全文本渲染；remote MCP wire 已手工验证 | 尚无真实浏览器 UI / XSS 端到端验收记录；remote MCP SDK 502 结论需同步到验收记录 |
| P1-T4 Provenance / Freshness | 待闭环 | repo、commit、file hash、索引时间和批次写入 citation；expected commit filter 已下推到 lexical / vector / symbol 检索并在排序前生效 | 未实现当前工作区或指定版本的 stale 最小判断；结果冲突 risk 仍待定义 |
| P1-T5 多仓共库隔离 | 已实现 | repo-scoped item / embedding identity 和 repo filter | 未发现原始范围内的直接缺口 |
| P1-T6 Incremental Indexing | 已实现 | `--path`、dry-run、file hash、范围清理和失败文件保留 | 未发现原始范围内的直接缺口 |
| P1-T7 Lexical / BM25 | 已完成 | 中文分词、工程 token、BM25-like 字段加权和候选预排序 | 向量路径不在本次验收范围 |
| P1-T8 Alias Mapping | 已完成 | JSON alias 配置、query expansion、公开 debug trace 和真实语料 alias 覆盖 | alias 来源治理仍留待后续阶段 |
| P1-T9 Symbol Index | 已完成 | catalog、索引、清理、exact / prefix lookup 和 symbol recall；Java item-aligned symbol 已在真实语料中覆盖 | `source_item_id is None` 的非 item catalog symbol 后续如有场景再扩展 |
| P1-T10 Multi-Recall / RRF / Trace | 已完成 | lexical / vector / symbol、RRF、完整 `RetrievalTrace` 和 API / Playground debug 展示 | 向量路径未在本次验收启用 |
| P1-T11 Context Composer | 待闭环 | token budget、citation 汇总、基础风险提示、primary / related / background evidence 分层、相同 source 去重 | 仍缺同文件重叠片段合并和多路召回重复候选闭环；这是原始成功标准，不是后续质量项 |
| P1-T12 Sufficiency / Confidence | 待闭环 | `MISSING_CONTEXT`、`LOW_CONFIDENCE`、`INCOMPLETE_PROVENANCE`、`STALE_INDEX`、`CROSS_REPO_RESULTS` 已结构化输出 | 仍缺结果冲突 risk，以及当前工作区或指定版本 stale 的最小闭环 |
| P1-T13 Code Graph Research | 已完成 | ADR-006 已明确 Phase 1 不直接集成 CodeGraph，仅作为 Phase 2 graph contract 参考 | 无 Phase 1 阻塞项 |

## 阶段验收前必须关闭的事项

1. 完成真实浏览器 Playground UI / XSS 端到端验收，并把浏览器版本、请求/响应摘要和结论写入 `docs/evaluation/playground-mcp-acceptance.md`。
2. 只有在允许真实调用 embedding provider 时，补充 embedding-enabled live evaluation；当前 no-embedding 验收不能证明向量召回质量。
3. 实现 `P1-T11` 同文件重叠片段合并最小闭环，确保相同 source、多路召回重复候选和重叠行区间不会重复消耗 token budget。
4. 实现 `P1-T12` 结果冲突 risk 与 stale 判断最小闭环，至少覆盖召回结果版本/来源冲突和当前工作区或指定版本不匹配的风险提示。
5. 定位 Python MCP SDK `streamablehttp_client` 对当前 remote MCP server 返回 502 的根因；如果是 ACP server 配置或 session/header 处理问题则修复，如果是 SDK/upstream 限制则补充可重复验证脚本或支持矩阵结论。

## 下一 session 实施入口

下一 session 应直接以本文为状态入口，不再另建 handoff 文档。

- worktree：`D:\Code\GitHub\agent-context-platform-phase1-smart-campus`
- branch：`deng/phase1-smart-campus-acceptance`
- 禁止在 `master` checkout 上实施 3 / 4 / 5。
- 不修改 `.env`，不真实请求 embedding provider；除非用户之后明确允许。
- `smart-campus` 真实项目验收必须显式传入 repo `github.com/BaSui01/smart-campus`，并使用 expected commit `95c69bb5dcfe943d32ab3a7e6947a29aeb140ae7`。
- 推荐先读：
  - `src/agent_context_platform/context_composer.py`
  - `src/agent_context_platform/api.py`
  - `src/agent_context_platform/retrieval.py`
  - `src/agent_context_platform/mcp_server.py`
  - `docs/planning/post-mvp-todo.md` 中 `P1-T3`、`P1-T4`、`P1-T11`、`P1-T12` 原始需求段落
- 行为变更必须先写失败测试，再实现。重点测试：
  - `P1-T11`：同文件重叠或相邻片段合并后不重复出现在 context / citations 中。
  - `P1-T12`：结果冲突 risk 和 stale risk 进入稳定 response。
  - MCP SDK：用 Python MCP SDK `streamablehttp_client` 复现并验证 `initialize`、`tools/list`、`tools/call`。

## 文档职责

- [后续待办与阶段规划](post-mvp-todo.md) 保留 Phase 1 原始任务边界和 Phase 2 待办。
- 本文是当前实现与验收缺口的唯一状态入口。
- README、架构设计和 Context API 文档只描述当前已实现的运行行为与公开契约，不将未完成项表述为既定能力。
