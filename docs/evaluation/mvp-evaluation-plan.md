# MVP 评测计划

## 目标

MVP 评测目标是验证 agent-context-platform 是否能为 Coding Agent 返回真实有用的工程上下文。

评测不以“回答看起来合理”为准，而以固定任务样本和期望来源引用为准。

## 评测集规模

第一版准备 10-20 个真实或半真实工程任务。

样本必须覆盖：

- 相似实现查找。
- 代码修改前上下文构建。
- 表结构相关任务。
- 设计文档相关任务。
- 跨代码、SQL、Markdown 的综合任务。

## 样本格式

每个样本使用 Markdown 或 JSON 保存，字段如下：

```json
{
  "id": "task-001",
  "task": "新增某地区支付接口，复用已有支付报文生成能力",
  "expected_hits": [
    {
      "source_type": "code",
      "path": "src/main/java/example/PaymentMessageBuilder.java",
      "symbol": "PaymentMessageBuilder.build"
    },
    {
      "source_type": "db_schema",
      "table": "payment_order"
    },
    {
      "source_type": "doc",
      "path": "docs/design/payment-integration.md",
      "heading_path": "Payment Integration > Message Generation"
    }
  ],
  "irrelevant_rules": [
    "与支付报文无关的账户查询实现",
    "只包含同名词但不属于当前业务链路的测试工具"
  ],
  "notes": "示例路径和名称必须脱敏。"
}
```

要求：

- 不写入真实企业内部项目名、表名或敏感标识。
- `expected_hits` 必须尽量使用来源引用，而不是自然语言描述。
- 如果一个任务只验证单资产能力，也必须说明不要求的资产类型。

## 指标

### Top5 命中率

定义：

```text
Top5 中至少命中一个 expected_hit 的样本数 / 样本总数
```

MVP 目标：

```text
Top5 命中率 >= 70%
```

### Top10 明显无关结果数量

定义：

```text
每个样本 Top10 中，被人工判定为明显无关的结果数量
```

MVP 目标：

```text
Top10 明显无关结果 <= 3 条
```

### 来源引用完整率

定义：

```text
包含有效 SourceCitation 的返回结果数 / 返回结果总数
```

MVP 目标：

```text
100%
```

无来源引用的上下文不能被 Agent 当作工程依据。

## 人工标注规则

人工标注只判断来源是否对当前任务有工程价值，不判断语言描述是否漂亮。

有效命中：

- 可作为相似实现参考。
- 可帮助定位需要修改的模块。
- 可说明相关表结构或字段约束。
- 可提供任务相关设计背景。

明显无关：

- 仅关键词相同但业务链路无关。
- 只命中测试工具或示例代码，且不能支撑当前任务。
- 文档主题相近但不包含当前任务需要的约束。
- 来源缺失，无法追溯。

## 回归流程

每次检索策略、索引器、Context Builder 变更后运行评测。

流程：

```text
准备脱敏语料
    ↓
重建离线索引
    ↓
运行评测任务集
    ↓
计算 Top5 命中率、Top10 无关结果、来源引用完整率
    ↓
输出失败样本详情
```

评测输出至少包含：

- 样本 ID。
- 查询任务。
- Top10 返回结果来源。
- 是否命中 expected hits。
- 明显无关结果数量。
- 缺失来源引用的结果。

## 通过标准

MVP 进入可试用状态前必须满足：

- Top5 命中率 >= 70%。
- Top10 明显无关结果 <= 3 条。
- 来源引用完整率 = 100%。
- `build-task-context` 能在至少 3 个综合任务中返回代码、SQL、Markdown 中的两类以上上下文。

## 失败处理

如果评测失败，优先排查顺序：

1. 索引器是否漏抽结构化字段。
2. 关键词搜索是否被向量结果压制。
3. 过滤条件是否过宽或过窄。
4. Context Builder 是否裁剪掉关键结果。
5. 评测样本的 expected hits 是否标注错误。

不要直接引入 GraphRAG 或复杂 rerank 作为第一反应。先确认基础索引和 Hybrid Search 是否正确。
