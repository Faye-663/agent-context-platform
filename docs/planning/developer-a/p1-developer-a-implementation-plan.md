# P1 开发者 A 实施计划

## 文档信息

| 项目 | 内容 |
|------|------|
| 对应方案 | `docs/planning/p1-developer-a-technical-design.md`（已评审通过） |
| 执行人 | 开发者 A |
| 目标 | 完成 P1-T1、P1-T2、P1-T3 的编码落地 |

---

## 实施概览

### 4 轮 11 步

| 轮次 | 步骤 | 内容 | 前置依赖 |
|------|------|------|---------|
| **第 1 轮** | 1-3 | evaluation.py 核心层增强 | 无 |
| **第 2 轮** | 4-6 | acp-eval CLI + pytest 回归 | 第 1 轮完成 |
| **第 3 轮** | 7-9 | Context API + MCP Contract 调整 | 第 1-2 轮（平行不阻塞） |
| **第 4 轮** | 10-11 | MCP Web Playground | 第 3 轮完成（需要 DebugOptions + `_trace`） |

### 关键路径

```
Step 1 → Step 2 → Step 3 → Step 4 → Step 5 → Step 6
                                                    │
Step 7 → Step 8 → Step 9（与第 1-2 轮可平行推进）    │
                                                    ▼
                                           Step 10 → Step 11
```

第 3 轮（MCP Contract）与第 1-2 轮（Evaluation）**无代码依赖**，可以平行推进。**建议策略**：

- 先做第 1 轮（evaluation.py 核心层），这是基础
- 第 2 轮和第 3 轮可以平行做，因为改的是不同文件
- 第 4 轮（Playground）需要第 3 轮的 contract 确定后再做

---

## 第 1 轮：evaluation.py 核心层增强

### Step 1：加载器 — `load_golden_tasks()`

**目标**：实现从 JSON 文件加载评测样本的能力。

**改动文件**：
- `src/agent_context_platform/evaluation.py` — 新增 `load_golden_tasks()` 函数
- `tests/test_evaluation.py` — 新增加载器测试

**验收标准**：
- 能正确加载 `eval/golden-tasks.json`（12 条样本，4 组）
- 校验 `schema_version`，不匹配时明确报错
- 校验 `id` 全局唯一，重复时明确报错
- 校验每个 sample 的必填字段（`id`、`task`、`expected_hits`）
- 返回 `dict[str, list[EvaluationSample]]` 结构，key 为 group 名
- 异常时抛出带上下文信息的错误（指出哪个文件、哪个样本、哪个字段有问题）

**测试要点**：
- 正常加载 12 条样本
- 加载空组（samples 为空数组）
- 加载缺失必填字段 → 抛出明确异常
- 加载重复 id → 抛出明确异常
- 加载不支持 schema_version → 抛出明确异常

---

### Step 2：MRR 指标 + top-k 可配置

**目标**：在现有 top-5 hit rate 基础上增加 MRR 指标，并让两个指标的 top-k 可配置。

**改动文件**：
- `src/agent_context_platform/evaluation.py`
  - `EvaluationReport` 增加 `mrr` 字段
  - `EvaluationSampleResult` 增加 `first_hit_rank` 字段
  - `evaluate_context_payloads()` 增加 `top_k` 参数（默认 5），替代硬编码的 5
  - `evaluate_context_payloads()` 增加 MRR 计算逻辑
  - 原有字段名 `top5_hit_rate` → `top_k_hit_rate`，`top10_irrelevant_result_count` → `top_k_irrelevant_result_count`
- `tests/test_evaluation.py` — 新增 MRR 测试用例

**验收标准**：
- `evaluate_context_payloads(top_k=5)` 和旧版 top-5 行为完全一致
- MRR 计算正确：
  - 期望证据排第 1 → MRR 贡献 1.0
  - 期望证据排第 3 → MRR 贡献 0.333
  - 期望证据未召回 → MRR 贡献 0
- 3 个样本 2 个命中 top-5 且排名分别为 1、3，MRR = (1.0 + 0.333) / 3 = 0.444
- `top_k=3` 时只检查 top-3，top-5 范围内的期望不在前 3 则不计为命中

**测试要点**：
- top_k=5 时和现有行为一致
- 不同 top_k 值的影响
- MRR 边界情况（全部命中第一、全部未命中、混合）

---

### Step 3：报告格式化 — `format_report()` / `format_grouped_reports()`

**目标**：将 `EvaluationReport` 格式化为 text / markdown / json 三种格式。

**改动文件**：
- `src/agent_context_platform/evaluation.py` — 新增 `format_report()` 和 `format_grouped_reports()` 函数
- `tests/test_evaluation.py` — 新增格式化测试

**输出格式示例**：

**text 格式**：
```
╔════════════════════════════════════════╗
║        ACP Evaluation Report          ║
╠════════════════════════════════════════╣
║ Passed:         YES                   ║
║ Top-5 hit rate: 0.75 (9/12)          ║
║ MRR:            0.6243               ║
║ Source citation completeness: 1.0     ║
║ Failed samples: code-003, doc-002    ║
╠════════════════════════════════════════╣
║ Groups:                                ║
║   code_search:       0.75 (3/4)      ║
║   db_schema_search:  1.00 (3/3)      ║
║   doc_search:        0.67 (2/3)      ║
║   task_context:      1.00 (2/2)      ║
╚════════════════════════════════════════╝
```

**markdown 格式**：
```markdown
# ACP Evaluation Report

| Metric | Value |
|--------|-------|
| Passed | YES |
| Top-5 hit rate | 0.75 (9/12) |
| MRR | 0.6243 |
| Source citation completeness | 1.0 |

## Failed samples
| ID | Task | Reason |
|----|------|--------|
| code-003 | 订单状态变更的入口在哪里 | Expected hit not found in top-5 |

## By group
| Group | Hit Rate | Passed |
|-------|----------|--------|
| code_search | 0.75 (3/4) | YES |
```

**json 格式**：`EvaluationReport.model_dump(mode="json")` 的直接输出，加外层组结构。

**验收标准**：
- text 格式：对齐工整，包含总体指标 + 失败列表 + 分组指标
- markdown 格式：表格完整，可直接粘贴到 MR 描述
- json 格式：所有数据可程序消费
- `format_grouped_reports()` 输出包含各组报告和汇总

**测试要点**：
- 全通过场景的报告输出
- 部分失败场景的报告输出
- 空结果场景
- 各组格式一致

---

## 第 2 轮：acp-eval CLI + pytest 回归

### Step 4：CLI 入口 — `evaluation_cli.py`

**目标**：实现 `acp-eval` 命令，可通过命令行运行评测。

**变动文件**：
- `src/agent_context_platform/evaluation_cli.py` — ★ 新建
- `pyproject.toml` — 注册 `acp-eval` 入口
- `tests/test_evaluation_cli.py` — ★ 新建

**CLI 参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--tasks` | str | 必填 | golden-tasks.json 路径 |
| `--api` | str | `http://127.0.0.1:8000` | Context API 地址 |
| `--top-k` | int | `5` | Top-k 范围 |
| `--min-hit-rate` | float | `0.7` | 通过阈值 |
| `--timeout` | int | `180` | 每条样本的超时秒数 |
| `--format` | str | `text` | 报告格式：text / markdown / json |
| `--output` | str | 无 | 输出文件路径（不传则 stdout） |
| `--validate-only` | flag | `false` | 仅校验样本文件格式，不调 API |

**实现要点**：
- 使用 `argparse` 解析参数（和 `index_cli.py` 风格一致）
- live mode 调用 `POST /build-task-context`，带 `--timeout` 控制
- 调用 `load_golden_tasks()` → `run_evaluation()` → `format_grouped_reports()`
- exit code 遵循方案约定（0=通过 / 1=失败 / 2=错误）
- 网络错误、JSON 解析错误等给出明确中文错误信息
- `--validate-only` 只执行格式校验（`load_golden_tasks()` 的校验逻辑），不连 API

**验收标准**：
- `acp-eval --help` 输出完整参数说明
- `acp-eval --validate-only --tasks eval/golden-tasks.json` 通过
- `acp-eval --tasks eval/golden-tasks.json --api http://...` 能正常跑通（依赖 Context API 运行）
- `--format markdown --output report.md` 正确输出文件
- `--timeout` 超时后给出明确提示
- API 不可达时给出明确错误信息
- exit code 正确（0/1/2）

**测试要点**：
- Mock HTTP 调用，测试 CLI 逻辑
- 各类参数组合
- 错误处理路径（API 不可达、JSON 格式错误）

---

### Step 5：pytest 回归入口

**目标**：实现 CI 可用的回归测试，确保评测样本达到最低标准。

**变动文件**：
- `tests/test_eval_regression.py` — ★ 新建

**实现内容**：

```python
# tests/test_eval_regression.py
"""CI 回归门禁：评测样本通过最低阈值。

运行方式：
  pytest tests/test_eval_regression.py --api-url http://...
"""

import os
import pytest
from agent_context_platform.evaluation import (
    load_golden_tasks, evaluate_context_payloads,
)


API_URL = os.environ.get("ACP_EVAL_API_URL", "http://127.0.0.1:8000")
MIN_HIT_RATE = float(os.environ.get("ACP_EVAL_MIN_HIT_RATE", "0.7"))


def test_all_groups_pass():
    tasks = load_golden_tasks("eval/golden-tasks.json")
    # 展平所有组
    all_samples = [s for group in tasks.values() for s in group]
    payloads = _collect_payloads(all_samples, API_URL)
    report = evaluate_context_payloads(all_samples, payloads, min_hit_rate=MIN_HIT_RATE)
    assert report.passed, (
        f"Failed samples: {report.failed_sample_ids}\n"
        f"Top-{report.top_k} hit rate: {report.top_k_hit_rate}\n"
        f"MRR: {report.mrr}"
    )


def test_each_group():
    tasks = load_golden_tasks("eval/golden-tasks.json")
    for group_name, samples in tasks.items():
        payloads = _collect_payloads(samples, API_URL)
        report = evaluate_context_payloads(samples, payloads, min_hit_rate=MIN_HIT_RATE)
        assert report.passed, (
            f"Group '{group_name}' failed: {report.failed_sample_ids}"
        )
```

**验收标准**：
- `pytest tests/test_eval_regression.py` 可运行
- 失败时给出明确的失败样本列表和指标

---

### Step 6：注册 `acp-eval` 到 `pyproject.toml`

**目标**：让 `acp-eval` 可用。

**变动文件**：
- `pyproject.toml` — 新增 `acp-eval` 入口

```toml
[project.scripts]
acp-index = "agent_context_platform.index_cli:main"
acp-mcp-server = "agent_context_platform.mcp_server:main"
acp-eval = "agent_context_platform.evaluation_cli:main"
```

**验收标准**：
- `pip install -e .` 或 `uv sync` 后 `acp-eval` 可执行

---

## 第 3 轮：MCP Tool Contract 调整

### Step 7：Context API — 新增 DebugOptions 和 `_trace`

**目标**：在 `api.py` 中增加 `DebugOptions` 模型，替代 `query_embedding` 顶级参数，并支持 `_trace` 响应。

**变动文件**：
- `src/agent_context_platform/api.py`
  - 新增 `DebugOptions` 模型
  - `SearchRequest` 中 `query_embedding` 移除，替换为 `debug_options: DebugOptions | None`
  - `BuildTaskContextRequest` 增加 `debug_options: DebugOptions | None`
  - `_search_endpoint()` 和 `build_task_context()` 中根据 `debug_options.include_trace` 注入 `_trace` 字段到 response
- `tests/test_context_api.py` — 新增 DebugOptions、`_trace` 相关测试

**`DebugOptions` 模型**：

```python
class DebugOptions(BaseModel):
    """调试参数分组，不传时使用默认行为。"""
    model_config = ConfigDict(extra="forbid")

    query_embedding: list[float] | None = None
    """显式提供 query embedding。通常由 ACP 内部自动生成，仅在测试或上游已生成向量的场景使用。"""

    include_trace: bool = False
    """是否在 response 中返回检索 trace。仅用于调试，结构可能随版本变化。"""
```

**`_trace` 注入逻辑**（在 `_search_endpoint()` 和 `build_task_context()` 中）：

```python
# search endpoint 的 response 构建
response = {"results": _dump_results(results)}
if request.debug_options and request.debug_options.include_trace:
    response["_trace"] = _build_trace(results, search_service)
return response

# build-task-context endpoint 的 response 构建
context_dict = context.model_dump(mode="json")
if request.debug_options and request.debug_options.include_trace:
    context_dict["_trace"] = _build_trace_for_context(context, search_service)
return context_dict
```

`_build_trace()` 函数从检索结果中提取 trace 信息。当前 trace 信息来源为 `RetrievalTrace`（`retrieval_trace.py` 中的内部结构）和 `SearchResult.score_parts`。

> **需要与开发者 C 对齐**：确认 `HybridSearchService.search()` 是否已返回 `RetrievalTrace`，或是否需要新增一个返回 trace 的接口。如果尚未暴露，Step 7 先实现参数结构调整（DebugOptions），`_trace` 注入逻辑暂缓。

**验收标准**：
- `debug_options=None`（不传）时，行为完全不变
- `debug_options={"include_trace": false}` 时，response 不变
- `debug_options={"include_trace": true}` 时，response 增加 `_trace` 字段
- `query_embedding` 不再出现在 `SearchRequest` 顶级，通过 `debug_options.query_embedding` 传入
- 原有 `query_embedding` 的测试需要迁移到 `debug_options` 路径

**测试要点**：
- 不传 debug_options → 兼容现有请求
- include_trace=false → 不返回 `_trace`
- include_trace=true → 返回 `_trace`
- debug_options.query_embedding 正常工作
- 向后兼容：旧版客户端不传 debug_options 不会报错

---

### Step 8：MCP Server — tool 签名调整

**目标**：同步 MCP Server 层的 tool 签名，移除 `query_embedding`，新增 `debug_options`。

**变动文件**：
- `src/agent_context_platform/mcp_server.py`
  - `ContextApiToolClient.search_code()` / `search_db_schema()` / `search_doc()` / `build_task_context()` 签名调整
  - `_post_search()` 序列化逻辑调整
  - MCP tool 函数（`@server.tool()` 装饰的四个函数）签名调整
- `tests/test_mcp_server.py` — 新增 debug_options 相关测试

**tool 签名变更**：

```python
# 调整前
def search_code(query, limit=10, filters=None, query_embedding=None, request_id=None)

# 调整后
def search_code(query, limit=10, filters=None, debug_options=None, request_id=None)
```

**序列化逻辑**：

```python
def _post_search(self, tool, path, *, query, limit, filters, debug_options, request_id):
    payload = {
        "query": query,
        "limit": limit,
        "filters": filters or {},
    }
    if debug_options is not None:
        payload["debug_options"] = debug_options
    if request_id is not None:
        payload["request_id"] = request_id
    return self._post_tool(tool, path, payload)
```

**验收标准**：
- `search_code(query="...")` 不传 `debug_options` 时兼容
- `search_code(query="...", debug_options={"include_trace": true})` 正确透传
- MCP tool description 不需要改动（只涉及参数，不涉及行为描述）

**测试要点**：
- 不传 debug_options 兼容
- debug_options 正确透传到 HTTP payload
- 四个 tool 签名一致

---

### Step 9：API 文档同步

**目标**：更新 `docs/api/context-api.md`，反映参数变更。

**变动文件**：
- `docs/api/context-api.md`

**变更内容**：
- `SearchRequest` 中移除 `query_embedding` 顶级字段，替换为 `debug_options` 描述
- 在字段说明表中增加 `debug_options` 行
- 在请求体 JSON 示例中更新参数
- 在"待确认项"中移除关于 `query_embedding` 和 trace 的待定标记（已确定）

**验收标准**：
- 文档描述的请求体参数与实际代码一致
- 不包含未实现的参数
- `_trace` 字段标注"调试用途，结构可能变化"

---

## 第 4 轮：MCP Web Playground

### Step 10：Playground 基础框架

**目标**：搭建 Playground 的基本页面结构：连接管理 + tool 选择 + 参数表单 + JSON 展示。

**变动文件**：
- `playground/index.html` — ★ 新建，主页面 HTML 结构
- `playground/style.css` — ★ 新建，页面样式
- `playground/app.js` — ★ 新建，MCP client 逻辑 + UI 渲染

**页面布局**：

```
┌─────────────────────────────────────────────────┐
│  [连接管理栏]                                    │
│  Server URL: [http://127.0.0.1:8001/mcp] [连接] │
│  状态: ● 已连接                                  │
├──────────────────┬──────────────────────────────┤
│  [Tool 列表]     │  [参数与结果区]                │
│                  │                              │
│  ○ search_code  │  [参数表单]                   │
│  ○ search_db_   │  query: [........]            │
│  ○ search_doc   │  limit: [10]                  │
│  ○ build_task_  │  ☐ Include Trace              │
│                  │  [调用]                       │
│                  │                              │
│                  │  [Response 展示]              │
│                  │  原始 JSON  | 可读化          │
│                  │  ┌──────────────────┐         │
│                  │  │                  │         │
│                  │  └──────────────────┘         │
└──────────────────┴──────────────────────────────┘
```

**功能实现**（app.js）：

```javascript
// 核心对象
class McpClient {
    constructor(serverUrl) { ... }
    async listTools() { ... }           // POST /mcp tools/list
    async callTool(name, args) { ... }  // POST /mcp tools/call
}

class PlaygroundApp {
    constructor() { /* 绑定 DOM 事件 */ }
    async connect() { /* 连接 MCP Server */ }
    async selectTool(toolName) { /* 切换 tool，更新参数表单 */ }
    async invoke() { /* 调用 tool，展示结果 */ }
    renderResults(response) { /* 渲染 JSON + 可读化视图 */ }
}
```

**验收标准**：
- 输入 URL → 点击连接 → 列出四个 tool
- 选择 tool → 自动生成参数表单（根据 tool 的 inputSchema）
- 填写参数 → 调用 → 显示原始 JSON response
- 调用失败时显示错误信息
- 连接失败时显示明确提示
- 页面不依赖任何构建工具，浏览器打开 `index.html` 即可使用
- 样式整洁，不同功能区域清晰可辨

---

### Step 11：Playground 可读化展示

**目标**：对四个 core tool 的结果做可读化展示，支持 `_trace` 折叠面板。

**变动文件**：
- `playground/app.js` — 增加可读化渲染函数
- `playground/style.css` — 增加 trace 折叠面板样式

**可读化展示内容**：

**search_code / search_db_schema / search_doc**：
```
结果列表（共 N 条）：
┌── #1 ─────────────────────────────────────────┐
│ Score:  0.82                                   │
│ Title:  PaymentMessageBuilder.build            │
│ Reason: 方法名和正文同时命中 payment/message    │
│ Path:   src/main/java/.../PaymentMessage...    │
│ Lines:  32-88                                  │
│ [展开详情]  [引用来源]                          │
└────────────────────────────────────────────────┘
```

**build_task_context**：
```
┌─ Tab: code [3] | db_schema [1] | doc [2] | similar [1] ─┐
│                                                            │
│ (当前 tab 内容，与 search 结果展示格式一致)                 │
│                                                            │
│ ⚠ risks: ["部分上下文缺少 file_hash"]                      │
│ ⚠ missing_context: []                                      │
└────────────────────────────────────────────────────────────┘
```

**Trace 展示**（折叠面板，勾选 Include Trace 时出现）：

```
▶ Trace Details（点击展开）
  ┌─────────────────────────────────────────┐
  │ Query Tokens: 支付, 报文, 构建, 方法    │
  │ Alias: 无                               │
  │ Channels:                               │
  │   lexical: 12 candidates, top=0.85      │
  │   vector:  8 candidates, top=0.72       │
  │   symbol:  3 candidates, top=1.0        │
  │ RRF Fused: 10 candidates                │
  └─────────────────────────────────────────┘
```

**验收标准**：
- search_code 的结果列表展示 title、score、match_reason、path
- build_task_context 的结果按四类资产分组 tab 展示
- `risks` 和 `missing_context` 高亮显示
- 勾选 Include Trace 后 trace 信息以折叠面板展示
- 原始 JSON 和可读化展示可通过 tab 切换

---

## 依赖与风险

### 外部依赖

| 步骤 | 依赖 | 缓解措施 |
|------|------|---------|
| Step 1-6 | 无 | 独立开发，不依赖 B/C |
| Step 7 | 开发者 C 的 `RetrievalTrace` 如何从 `HybridSearchService` 获取 | 如果 C 尚未暴露 trace，Step 7 可以先只做参数结构调整（DebugOptions），`_trace` 注入逻辑等到 C 提供接口后再补 |
| Step 8 | 无 | MCP 层只做参数透传，不依赖 retrieval 内部逻辑 |
| Step 9 | 无 | 纯文档变更 |
| Step 10-11 | Step 7-8 完成 | DebugOptions 和 `_trace` 字段稳定后才能在 Playground 中展示 trace |

### 风险

| 风险 | 影响 | 应对 |
|------|------|------|
| 第 3 轮开始时开发者 C 的 `RetrievalTrace` 尚未通过 API 可获取 | `_trace` 注入逻辑无法实现 | 先实现 DebugOptions 参数结构调整，`_trace` 注入加 `# TODO` 标记，等 C 就绪后再补。Playground 的 trace 展示也同步延迟 |
| 评测时需要 Context API 运行且有索引数据 | 开发阶段无法端到端验证 | 单元测试用 mock payload 覆盖核心逻辑。CLI 的 live mode 测试依赖 CI 环境 |
| `golden-tasks.json` 中的 mock 样本与实际项目差异大 | 后续切换时需调整样本 | 样本结构已预留，只需替换 `task` 和 `expected_hits` 的具体值，组结构不变 |

---

## 交付清单

| 步骤 | 交付物 | 类型 |
|------|--------|------|
| Step 1 | `evaluation.py` 新增 `load_golden_tasks()` | 代码 |
| Step 1 | `test_evaluation.py` 新增加载器测试 | 测试 |
| Step 2 | `evaluation.py` 增强 `evaluate_context_payloads()` + MRR | 代码 |
| Step 2 | `test_evaluation.py` 新增 MRR 测试 | 测试 |
| Step 3 | `evaluation.py` 新增 `format_report()` / `format_grouped_reports()` | 代码 |
| Step 3 | `test_evaluation.py` 新增格式化测试 | 测试 |
| Step 4 | `evaluation_cli.py`（`acp-eval`） | 代码 |
| Step 4 | `test_evaluation_cli.py` | 测试 |
| Step 5 | `test_eval_regression.py` | 测试 |
| Step 6 | `pyproject.toml` 注册 `acp-eval` | 配置 |
| Step 7 | `api.py` 新增 `DebugOptions`、`_trace` 响应 | 代码 |
| Step 7 | `test_context_api.py` 新增 DebugOptions 测试 | 测试 |
| Step 8 | `mcp_server.py` 签名调整 | 代码 |
| Step 8 | `test_mcp_server.py` 新增 debug_options 测试 | 测试 |
| Step 9 | `docs/api/context-api.md` 同步更新 | 文档 |
| Step 10 | `playground/index.html` / `style.css` / `app.js` | 前端 |
| Step 11 | playground 可读化展示 + trace 面板 | 前端 |

---

## 验证方式

### 每步验证

每个 Step 完成后：

1. 新增的单元测试全部通过：`uv run pytest tests/test_xxx.py -v`
2. 不影响已有测试：`uv run pytest` 全部通过（当前基线 112 passed）
3. lint 检查：代码风格与现有代码一致（import 顺序、type hint、docstring）

### 端到端验证

每一轮完成后：

| 轮次 | 验证方式 |
|------|---------|
| **第 1 轮完成** | `acp-eval --validate-only --tasks eval/golden-tasks.json` 通过 |
| **第 2 轮完成** | `pytest tests/test_eval_regression.py` 可运行（依赖 Context API） |
| **第 3 轮完成** | MCP tool 调用的 HTTP payload 中 `query_embedding` 不再出现在顶级，`debug_options` 正确透传 |
| **第 4 轮完成** | Playground 可通过浏览器打开，连接到 streamable-http MCP Server，调用 tool 并看到结果 |
