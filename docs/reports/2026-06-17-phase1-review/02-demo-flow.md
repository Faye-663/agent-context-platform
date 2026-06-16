# 演示流程

## 演示目标

让听众看清楚系统做了两件事：

1. 把工程材料离线索引成可追溯的结构化上下文。
2. 让 Agent 或人通过 API / MCP 查询这些上下文，并看到来源、风险和缺失信息。

## 推荐演示顺序

### 1. 展示当前入口

打开项目 README，说明三个入口：

- `acp-index`：离线索引真实工程材料。
- Context API：提供 `/search-code`、`/search-db-schema`、`/search-doc`、`/build-task-context`。
- MCP server / Playground：给 Agent 或开发人员调试使用。

### 2. 展示索引链路

说明命令形态：

```powershell
uv run acp-index --root D:\Code\YourProject --repo gitlab.example.com/group/project
```

重点解释：

- `--root` 是本机 checkout 路径。
- `--repo` 是稳定 repo identity，跨电脑不变。
- 索引结果包含 file hash、index time、batch id。
- symbol catalog 会记录 Java / SQL declarations。

### 3. 展示检索链路

在 Swagger 或 MCP Playground 中调用：

- `search_code`
- `search_db_schema`
- `search_doc`
- `build_task_context`

推荐问题：

```text
新增支付宝支付接口，复用已有支付报文生成能力
```

讲解返回结果：

- `related_code`
- `related_db_schema`
- `related_docs`
- `similar_implementations`
- `missing_context`
- `risks`
- `citations`

### 4. 展示检索解释

如果开启 `debug_options.include_trace=true`，响应会带 `_trace`。

当前 `_trace` 可以展示 channel score 摘要；后续会接入更详细的 retrieval trace，包括：

- query tokens
- alias expansions
- lexical / vector / symbol channel ranks
- RRF 融合信息

### 5. 展示评测入口

说明已有固定任务集：

```text
eval/golden-tasks.json
```

离线校验：

```powershell
uv run acp-eval --tasks eval/golden-tasks.json --validate-only
```

有真实 Context API 时运行 live evaluation：

```powershell
uv run acp-eval --tasks eval/golden-tasks.json --api http://127.0.0.1:8000
```

### 6. 结论

收束到一句话：

```text
系统已经能把工程材料索引成带来源的上下文，并通过多路召回和 Context Composer 给 Agent 使用；下一步是用真实项目数据评测召回质量。
```

## 注意事项

- 不要把 Playground 讲成正式产品后台，它当前是调试入口。
- 不要承诺 GraphRAG、权限系统、实时索引，这些不在当前 Phase 1 范围。
- 如果现场没有真实数据库，重点展示接口契约、评测文件和测试结果，不强行演示 live indexing。
