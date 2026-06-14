# P1 开发者 A — 评测、MCP Contract、Playground 技术方案

## 文档信息

| 项目 | 内容 |
|------|------|
| 编写人 | 开发者 A |
| 状态 | **已评审通过** |
| 对应阶段 | Phase 1（生产化建设） |
| 对应任务 | P1-T1、P1-T2、P1-T3 |
| 协作依赖 | 消费开发者 C 产出的 `RetrievalTrace` 和 `ContextComposer` 输出；消费开发者 B 产出的 provenance 字段 |

---

## 适用范围

本文描述开发者 A 在 Phase 1 中三个任务的实现方案，面向协作评审。评审通过后转入实施计划。

本文不涉及：

- 检索 ranking 算法设计（归开发者 C）
- 索引数据模型与 storage schema（归开发者 B）
- Symbol catalog 写入与清理（归开发者 B）
- Code graph 实现（Phase 2）

---

## 总览：三个任务的关系

```
P1-T1 Evaluation Harness（评测框架）
    └── 定义"什么算好检索"，是后续所有优化的衡量标准
    └── 建议最先做，后续改任何检索参数都能知道效果变化

P1-T2 MCP Tool Contract（工具契约）
    └── 定义 Agent 和 ACP 之间的接口协议
    └── Playground 要展示的内容、Evaluation 要评测的字段，都取决于 contract
    └── 建议第二做

P1-T3 MCP Web Playground（调试界面）
    └── 消费 P1-T2 的 contract、展示 P1-T1 的评测结果
    └── 建议最后做，避免前两个还未定型就做 UI 导致返工
```

---

## 一、P1-T1: Evaluation Harness / Golden Task Set

### 1.1 现状分析

现有 `evaluation.py` 已有基础能力：

- `EvaluationSample` / `ExpectedHit` — 评测样本的 Pydantic 模型
- `EvaluationReport` — 评测报告模型（含 `top5_hit_rate`、`source_citation_completeness`、`passed`）
- `evaluate_context_payloads()` — 给定样本和 payload 计算指标的核心函数
- `test_evaluation.py` — 两个单元测试验证基础逻辑

**当前缺失**：

- Golden task set 评测样本数据（目前只有测试中的硬编码）
- 样本加载器（从外部文件加载并校验）
- CLI 运行入口（`acp-eval` 命令）
- MRR 指标计算
- 格式化报告输出（text / markdown / json）
- pytest 回归入口

### 1.2 Golden Task Set（评测样本集）

#### 1.2.1 存储位置

```
agent-context-platform/
├── eval/                          # ★ 新建：独立评测目录
│   ├── golden-tasks.json          # 评测样本集
│   └── baseline/                  # 预留：基线 payload 存档目录
│       └── .gitkeep
├── src/agent_context_platform/
│   ├── evaluation.py              # ★ 增强：核心评测逻辑
│   └── ...
```

#### 1.2.2 JSON 格式

```json
{
  "schema_version": 1,
  "groups": {
    "code_search": {
      "description": "代码搜索场景——测试代码符号、中英混合、路径匹配",
      "samples": [
        {
          "id": "code-001",
          "task": "查找支付报文构建方法",
          "expected_hits": [
            {
              "source_type": "code",
              "symbol": "PaymentMessageBuilder.build"
            }
          ],
          "irrelevant_result_ids": ["code:AccountQueryService.query"],
          "irrelevant_rules": ["账户查询不属于支付报文生成链路"],
          "notes": "测试 symbol 精确命中"
        }
      ]
    },
    "db_schema_search": {
      "description": "表结构搜索场景",
      "samples": [
        {
          "id": "schema-001",
          "task": "查退款订单表结构",
          "expected_hits": [
            {
              "source_type": "db_schema",
              "table": "refund_order"
            }
          ],
          "notes": "测试表名精确命中"
        }
      ]
    },
    "doc_search": {
      "description": "文档搜索场景",
      "samples": []
    },
    "task_context": {
      "description": "聚合检索场景——测试 build-task-context 端到端",
      "samples": []
    }
  }
}
```

**设计要点**：

- `schema_version` 用于后续 format 变更时向前兼容
- 按 `groups` 分组，每种资产类型独立统计，方便定位薄弱通道
- 每个 sample 的 `id` 全局唯一（建议前缀 `code-` / `schema-` / `doc-` / `context-`）
- 预留 `irrelevant_result_ids` 和 `irrelevant_rules`，**Phase 1 暂不纳入自动评测指标**，仅记录

#### 1.2.3 样本数量

第一版 12 条，覆盖以下分布：

| 组 | 数量 | 覆盖场景 |
|----|------|---------|
| `code_search` | 4 条 | 类名精确、方法名、中英混合、路径片段 |
| `db_schema_search` | 3 条 | 表名、字段名、业务实体 |
| `doc_search` | 3 条 | 章节标题、文档内容、设计决策 |
| `task_context` | 2 条 | 聚合检索端到端 |

后续可扩展，不限制组名和样本数量。

### 1.3 核心层增强（evaluation.py）

在现有 `evaluate_context_payloads()` 基础上新增：

#### 1.3.1 新增函数

```python
def load_golden_tasks(path: str | Path) -> dict[str, list[EvaluationSample]]
    """从 JSON 文件加载评测样本集。
    
    - 校验 schema_version
    - 按 groups 解析，返回 {group_name: [samples]}
    - 校验每个 sample 的必填字段
    - 校验 id 全局唯一
    - 异常时抛出明确错误信息
    """

def run_evaluation(
    tasks: dict[str, list[EvaluationSample]],
    api_base_url: str,
    *,
    top_k: int = 5,
) -> dict[str, EvaluationReport]
    """实时模式：调用 Context API 收集 payload 并计算指标。
    
    - 对每条样本调用 build-task-context
    - 收集返回 payload
    - 调用 evaluate_context_payloads() 计算指标
    - 返回 {group_name: report} 结构
    """

def format_report(
    report: EvaluationReport,
    group_name: str | None = None,
    fmt: str = "text",
) -> str
    """将 EvaluationReport 格式化为可读文本。
    
    支持格式：
    - text：终端友好，表格+摘要
    - markdown：适合写入 MR
    - json：适合程序消费
    """

def format_grouped_reports(
    group_reports: dict[str, EvaluationReport],
    fmt: str = "text",
) -> str
    """多组汇总报告，包含：
    
    - 总体指标（所有样本合并）
    - 各组指标（分资产类型展示）
    - 失败样本列表及原因
    """
```

#### 1.3.2 现有函数改动

`evaluate_context_payloads()` 需要增强：

- `top_k` 参数从硬编码 5 改为可配置（默认 5）
- 增加 MRR 计算结果到 `EvaluationReport`
- 新增阈值参数名：`min_hit_rate`（替代 `min_top5_hit_rate`）

```python
# EvaluationReport 新增字段
class EvaluationReport(BaseModel):
    sample_count: int
    passed: bool
    top_k_hit_rate: float       # 原 top5_hit_rate，改为 top_k 可配置
    mrr: float                  # ★ 新增：Mean Reciprocal Rank
    top_k_irrelevant_result_count: int  # 原 top10_...，改为 top_k 可配置
    source_citation_completeness: float
    failed_sample_ids: list[str]
    samples: list[EvaluationSampleResult]
```

### 1.4 CLI 入口（acp-eval）

#### 1.4.1 命令设计

```bash
# 基本用法（live mode）
acp-eval --tasks eval/golden-tasks.json \
         --api http://127.0.0.1:8000

# 指定 top-k 和报告格式
acp-eval --tasks eval/golden-tasks.json \
         --api http://127.0.0.1:8000 \
         --top-k 3 \
         --format markdown \
         --output eval/report-20260613.md

# 仅校验样本文件格式（不调用 API）
acp-eval --tasks eval/golden-tasks.json \
         --validate-only
```

#### 1.4.2 预留参数（Phase 1 不实现，接口预留）

```bash
# Offline mode（Phase 2 或后续实现）
acp-eval --tasks eval/golden-tasks.json \
         --payloads eval/baseline-payloads.json

# 保存 payload（建立 baseline）
acp-eval --tasks eval/golden-tasks.json \
         --api http://127.0.0.1:8000 \
         --save-payloads eval/baseline-payloads.json
```

#### 1.4.3 注册方式

在 `pyproject.toml` 中添加：

```toml
[project.scripts]
acp-index = "agent_context_platform.index_cli:main"
acp-mcp-server = "agent_context_platform.mcp_server:main"
acp-eval = "agent_context_platform.evaluation_cli:main"  # ★ 新增
```

#### 1.4.4 exit code

| 条件 | exit code |
|------|-----------|
| 所有样本通过阈值 | 0 |
| 存在失败样本 | 1 |
| 参数错误或 API 不可达 | 2 |

#### 1.4.5 live mode 调用链路

```
acp-eval
  → 加载 golden-tasks.json
  → 对每条 sample 调用 POST /build-task-context
  → 收集 payloads
  → 调用 evaluate_context_payloads() 计算指标
  → 调用 format_report() 输出
  → exit code
```

### 1.5 pytest 回归入口

```python
# tests/test_eval_regression.py

class TestGoldenTaskRegression:
    """CI 回归门禁：评测样本必须通过最低阈值。"""

    def test_all_groups_pass_minimum_bar(self):
        """所有组的评测样本整体通过最低 hit rate 阈值。"""
        tasks = load_golden_tasks("eval/golden-tasks.json")
        payloads = call_api_and_collect(tasks, api_base_url="http://127.0.0.1:8000")
        # flatten all groups
        all_samples = [s for group in tasks.values() for s in group]
        report = evaluate_context_payloads(all_samples, payloads, min_hit_rate=0.7)
        assert report.passed, f"Failed samples: {report.failed_sample_ids}"

    def test_each_group_meets_minimum_hit_rate(self):
        """每个组（资产类型）单独通过最低阈值，便于定位薄弱资产类型。"""
        ...
```

### 1.6 迁移说明

- 现有 `test_evaluation.py` 中的单元测试保持不变（测试核心逻辑）
- `test_eval_regression.py` 是新增文件，用于 CI 回归（测试端到端评测链路）
- `EvaluationSample` / `ExpectedHit` 模型与 JSON 格式兼容，无需迁移

### 1.7 评审确认的最终决策

| # | 决策 | 结论 |
|---|------|------|
| A1 | `min_hit_rate` 阈值 | **0.7**，后续根据实际基线调整 |
| A2 | `--top-k` 默认值 | **5**，和现有 `top5_hit_rate` 一致 |
| A3 | Offline mode 参数注册 | **只预留说明文档**，参数不注册到 argparse，避免未实现的功能出现在 `--help` 中 |
| A4 | 超时控制 | CLI 层面加 **`--timeout`** 参数，默认 **180s** |
| A5 | 首次样本编写 | 开发者 A 先编写 **12 条 mock 样本**跑通流程，后续用真实案例替换 |

---

## 二、P1-T2: MCP Tool Contract 优化

### 2.1 现状分析

现有 `mcp_server.py` 中四个 tool 已有：

- 完整的中文 description（适用场景/不适用/输入建议/输出使用/兜底策略）
- 测试 `test_mcp_tool_descriptions_guide_agent_tool_selection` 验证了 description 覆盖度
- `ContextApiError` 区分错误码
- `McpTraceLogger` 支持 JSONL 调试日志
- `McpServerSettings` 完善的环境变量配置

**当前标注为"待优化"的原因**：

- `query_embedding` 作为顶级参数暴露给日常使用者，实际是高级调试功能
- retrieval trace 是内部结构，无法通过 API 获取
- response 中缺少 debug 模式下的 trace 字段
- 参数结构没有区分"常规参数"和"调试参数"

### 2.2 改动范围

#### 2.2.1 Context API 层（api.py）

新增 `DebugOptions` 模型：

```python
class DebugOptions(BaseModel):
    """调试参数分组，不传时使用默认行为。"""
    query_embedding: list[float] | None = None
    """显式提供 query embedding。通常由 ACP 内部自动生成，仅在测试或上游已生成向量的场景使用。"""
    include_trace: bool = False
    """是否在 response 中返回检索 trace（包含 tokenization、alias expansion、各通道排名和 RRF 融合细节）。仅用于调试。"""


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    debug_options: DebugOptions | None = None       # ★ 新增，替代 query_embedding
    request_id: str | None = None


class BuildTaskContextRequest(BaseModel):
    task: str = Field(min_length=1)
    limits: dict[str, int] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    debug_options: DebugOptions | None = None       # ★ 新增
    request_id: str | None = None
```

#### 2.2.2 Context API Response 变动

当 `debug_options.include_trace=true` 时，response 中增加 `_trace` 字段：

```json
{
  "results": [...],
  "_trace": {
    "query": "支付报文构建方法",
    "query_tokens": ["支付", "报文", "构建", "方法", "payment", "message", "build"],
    "alias_expansions": [],
    "channels": {
      "lexical": {"candidates": 12, "top_score": 0.85},
      "vector": {"candidates": 8, "top_score": 0.72},
      "symbol": {"candidates": 3, "top_score": 1.0}
    },
    "fused": [
      {
        "item_id": "code:PaymentMessageBuilder.build",
        "rrf_score": 0.0325,
        "channel_ranks": {"lexical": 1, "vector": 3},
        "channel_scores": {"lexical": 0.85, "vector": 0.72}
      }
    ]
  }
}
```

**说明**：

- `_trace` 以下划线开头，语义上标识为调试/内部字段
- 字段结构参考 `retrieval_trace.py` 中的 `RetrievalTrace` / `FusedCandidate` / `RecallHit`，但进行序列化友好调整
- 默认 `include_trace=false` 时 response 不变，不产生 breaking change
- `_trace` 结构在 Phase 1 允许迭代，不作为长期公开承诺

#### 2.2.3 MCP Server 层（mcp_server.py）

tool 签名调整：

```python
# 当前
def search_code(
    query: str,
    limit: int = 10,
    filters: dict[str, Any] | None = None,
    query_embedding: list[float] | None = None,  # ← 移除
    request_id: str | None = None,
) -> dict[str, Any]:

# 调整后
def search_code(
    query: str,
    limit: int = 10,
    filters: dict[str, Any] | None = None,
    debug_options: dict[str, Any] | None = None,  # ★ 新增
    request_id: str | None = None,
) -> dict[str, Any]:
```

`ContextApiToolClient` 内部序列化逻辑调整：

```python
# _post_search 方法
payload: dict[str, Any] = {
    "query": query,
    "limit": limit,
    "filters": filters or {},
}
if debug_options is not None:
    payload["debug_options"] = debug_options  # 透传整个 dict
if request_id is not None:
    payload["request_id"] = request_id
```

四个 tool（`search_code` / `search_db_schema` / `search_doc` / `build_task_context`）签名同步更新。

### 2.3 不变的部分

- **MCP description 内容不修改**（已验证覆盖"适用场景/不适用/输入建议/输出使用/兜底策略"）
- **公开响应结构不改变**（`results` / `related_code` / `missing_context` / `citations` 等字段保持现有 schema）
- **错误码体系不改变**（`invalid_request` / `embedding_unavailable` / `storage_unavailable`）
- **MCP JSONL 调试日志不改变**

### 2.4 评审确认的最终决策

| # | 决策 | 结论 |
|---|------|------|
| B1 | `_trace` 文档化策略 | **先不在正式契约中文档化**，标注"调试用途，结构可能变化"。等 trace 结构稳定后再纳入正式 doc |
| B2 | `include_trace` 适用范围 | **四个 endpoint 都支持**（search_code / search_db_schema / search_doc / build_task_context） |
| B3 | `_trace.fused` 与 `results` 的对齐方式 | **保持一致**：fused 列表按顺序对应最终返回结果中的每个 item，不包含被 RRF 裁剪掉的候选 |
| B4 | `DebugOptions` 扩展性 | **预留扩展空间**（保持 dict 透传风格，`DebugOptions` 内部使用 `extra=forbid`，扩展时转为具体字段） |

---

## 三、P1-T3: MCP Web Playground

### 3.1 现状分析

- **当前状态**：完全未实现
- **用户链路**：开发者 → 浏览器 → Playground → streamable-http → MCP Server → Context API

### 3.2 范围边界

**是**：

- 连接本地或指定的 MCP Server（streamable-http）
- 列出 MCP tools
- 开发者手动填写 tool 参数并调用
- 展示完整 request / response JSON
- 对 `search_code` / `search_db_schema` / `search_doc` / `build_task_context` 的结果做轻量可读化展示
- `include_trace=true` 时展示 trace 信息
- 一次性调用展示（不保存调试会话）

**不是**：

- 不是 Agent workflow replay
- 不是 LLM 调用平台
- 没有权限、多租户、审计
- 不保存调试会话（Phase 1 不做持久化）
- 不支持 stdio transport

### 3.3 架构

```
┌─────────────┐     fetch HTTP      ┌──────────────────┐
│  浏览器     │ ──────────────────→ │  MCP Server      │
│  Playground │                     │  (streamable-http)│
│  HTML+JS    │ ←────────────────── │  → Context API   │
└─────────────┘     JSON response   └──────────────────┘
```

**没有后端代理**，浏览器直接通过 HTTP 调用 MCP Server。

### 3.4 功能列表

#### F1：连接管理

- 输入 MCP Server URL（默认 `http://127.0.0.1:8001/mcp`）
- "连接"按钮触发 tools 列表加载
- 显示连接状态（已连接/连接失败）

#### F2：Tool 选择与参数填写

- 列出所有可用 tool（目前固定四个）
- 选中 tool 后显示其 description 和参数表单
- 参数表单按 tool 的 input schema 动态生成
- 填写参数 → 点击"调用"→ 显示结果

#### F3：Response 展示

- 原始 JSON 展示（格式化 + 语法高亮）
- **可读化展示**（对四个 core tool 的特殊处理）：
  - 结果列表展示（标题、score、match_reason、来源路径）
  - 点击展开 item 详情
  - `missing_context` 和 `risks` 高亮

#### F4：Debug 模式

- 勾选 "Include Trace" 后自动传 `debug_options.include_trace=true`
- trace 信息以折叠面板展示（tokenization、alias、通道排名、RRF）

### 3.5 技术栈建议

鉴于纯前端、单页面、无后端代理的需求，建议以下方案：

| 方案 | 优缺点 |
|------|--------|
| **纯 HTML + JS（单页）** | 零构建、零依赖、快速出原型。但组件化和状态管理靠手写 |
| **React/Vue + Vite** | 组件化好、生态丰富、适合后续扩展。需要构建步骤，但 Vite 开发体验轻量 |

**倾向建议**：纯 HTML + JS 起步，因为：

- Playground 是开发调试工具，非面向用户的产品
- 页面交互相对简单（一个表单 + 一个结果展示区）
- 零构建、零依赖意味着"git clone 后用浏览器打开就能用"
- Phase 1 结束后如果有扩展需求，再迁移到框架也不晚

**如果团队熟悉 React/Vue，也可以直接上框架**，此处不做硬性规定，由评审决定。

### 3.6 存放位置

```
agent-context-platform/
├── playground/                     # ★ 新建目录
│   ├── index.html                  # 主页面
│   ├── style.css                   # 样式
│   └── app.js                      # 逻辑（MCP client、UI 渲染）
├── ...
```

### 3.7 与 API 的交互示例

```
// 列出 tools（MCP 标准协议）
POST http://127.0.0.1:8001/mcp
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}

// 调用 tool
POST http://127.0.0.1:8001/mcp
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "search_code",
    "arguments": {
      "query": "支付报文生成",
      "limit": 5,
      "debug_options": {
        "include_trace": true
      }
    }
  }
}
```

### 3.8 评审确认的最终决策

| # | 决策 | 结论 |
|---|------|------|
| C1 | 技术栈 | **纯 HTML + JS 起步**，零构建零依赖 |
| C2 | MCP Server 默认地址 | 页面输入框默认值设为 **`http://127.0.0.1:8001/mcp`**，可在页面中修改 |
| C3 | 预设样本功能 | **Phase 1 不做**，后续再考虑 |
| C4 | 四类资产展示方式 | **按四类资产分组 tab 展示**，和 TaskContext 结构一致 |
| C5 | 多 Server 切换 | **Phase 1 只支持同时连接一个 Server** |

---

## 四、跨任务依赖与协作边界

### 4.1 内部依赖

```
P1-T1（Evaluation）
  └── 依赖 Context API 的 /build-task-context endpoint 可用
  └── 依赖开发者 C 的 retrieval trace 输出（如果评测要展示 trace 字段才有）

P1-T2（MCP Contract）
  └── 依赖当前 mcp_server.py 基线
  └── 依赖 api.py 中 SearchRequest / BuildTaskContextRequest 的参数模型

P1-T3（Playground）
  └── 依赖 P1-T2 调整后的 contract（debug_options 参数、_trace 响应字段）
  └── 依赖 MCP Server 以 streamable-http 模式可访问
```

### 4.2 与开发者 B 的协作边界

| 开发者 A 消费 | 由 B 提供 |
|-------------|-----------|
| `SourceCitation` 中的 provenance 字段 | `repo` / `branch` / `commit_sha` / `file_hash` / `indexed_at` / `index_batch_id` |
| `repo` 过滤行为 | `filters.repo` / `constraints.repo` / `ACP_DEFAULT_REPO` / `ACP_REQUIRE_REPO_FILTER` |

**约定**：

- 开发者 A 不额外定义 provenance response shape，直接消费 `SourceCitation` 中的字段
- `branch` / `commit_sha` 是 best-effort Git provenance，非 Git 目录允许为空
- A 的 Evaluation 中 provenance 完整性指标基于 `file_hash` 和 `indexed_at`，不因 `branch` / `commit_sha` 为空判定失败

### 4.3 与开发者 C 的协作边界

| 开发者 A 消费 | 由 C 提供 |
|-------------|-----------|
| `SearchResult.score_parts` | lexical / vector / symbol / rrf 分数分解 |
| `RetrievalTrace`（调参用） | query tokens / alias expansions / channel ranks / RRF 融合信息 |
| `TaskContext.risks` / `missing_context` | 上下文充分性判断 |
| Context Composer 输出 | 裁剪后的四类结果和 token budget 信息 |

**约定**：

- 开发者 A 不负责设计 retrieval ranking 算法
- 开发者 C 提供内部 `RetrievalTrace` 结构；A 负责在 API/Payload 层面序列化为 `_trace` 字段
- `_trace` 的 schema 由 A 和 C 共同确认，确保 C 产出的 trace 信息可以无损映射到 API response

---

## 五、建议的实施顺序

| 轮次 | 内容 | 涉及文件 |
|------|------|---------|
| 第 1 轮 | Golden task JSON 定义 + evaluation.py 增强（加载/报告/MRR） | `eval/golden-tasks.json`、`evaluation.py`、`test_evaluation.py` |
| 第 2 轮 | `acp-eval` CLI 入口 + pytest 回归 | `evaluation_cli.py`、`pyproject.toml`、`test_eval_regression.py` |
| 第 3 轮 | Context API + MCP Server contract 调整（DebugOptions、_trace） | `api.py`、`mcp_server.py`、`test_mcp_server.py`、`docs/api/context-api.md` |
| 第 4 轮 | MCP Web Playground | `playground/index.html`、`style.css`、`app.js` |

---

## 六、交付清单

| 交付物 | 对应任务 | 类型 |
|--------|---------|------|
| `eval/golden-tasks.json` | P1-T1 | 样本数据 |
| `evaluation.py` 增强（加载器、MRR、报告格式化） | P1-T1 | 代码 |
| `evaluation_cli.py`（`acp-eval` 入口） | P1-T1 | 代码 |
| `pyproject.toml` 新增 `acp-eval` 入口 | P1-T1 | 配置 |
| `tests/test_eval_regression.py` | P1-T1 | 测试 |
| `api.py` 新增 `DebugOptions`、`_trace` 响应 | P1-T2 | 代码 |
| `mcp_server.py` tool 签名调整（debug_options） | P1-T2 | 代码 |
| `docs/api/context-api.md` 同步更新 | P1-T2 | 文档 |
| `playground/index.html`、`style.css`、`app.js` | P1-T3 | 前端 |
| 对应单元测试 | 全部 | 测试 |
