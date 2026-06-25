# smart-campus 差距验收语料

本语料固定使用 `github.com/BaSui01/smart-campus` 的提交 `95c69bb5dcfe943d32ab3a7e6947a29aeb140ae7`。评测标签只保存公开路径、symbol、table 和 Markdown heading，不复制源码正文。

## 索引边界

- 索引 `backend`、`docs`、`README.md`、`CLAUDE.md` 中的 Java、PostgreSQL SQL DDL 和 Markdown。
- 排除 `src/test`、MySQL 和 Oracle migration；不启用 embedding。
- 必须显式传入 `--repo github.com/BaSui01/smart-campus`，不得依赖目录名或 `ACP_DEFAULT_REPO`。

## 运行约束

`acp-index` 和 Context API 不会自动加载 `.env`。执行前将 `.env` 加载到当前进程；启动验收专用 Context API 时移除全部 `ACP_EMBEDDING_*` 变量，设置 `ACP_REQUIRE_REPO_FILTER=true`，且不设置 `ACP_DEFAULT_REPO`。同时必须将 `ACP_ALIAS_FILE` 指向 `eval/corpora/smart-campus/aliases.json`，否则“智能助手”“校园门禁”等已标注别名不会参与 query expansion。

在 Codex Windows sandbox 中，Git 子进程需要进程级 `safe.directory` 配置读取固定 commit，不能修改 Git global config。

## 当前评测命令

```powershell
uv run acp-eval `
  --tasks eval/corpora/smart-campus/tasks.json `
  --repo github.com/BaSui01/smart-campus `
  --expected-commit 95c69bb5dcfe943d32ab3a7e6947a29aeb140ae7 `
  --format markdown
```
