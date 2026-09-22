# DSFlow 的 Claude Code 插件

把 `dsflow-project` skill、改讲解时自动体检的 hook、`dsflow mcp` 服务打成一个插件，装一次就在任何目录可用（hook 只对 guide.yaml 起作用，和数据科学无关的项目不受影响）。

```
claude --plugin-dir <仓库目录>/plugin      # 启动 Claude Code 时挂上这个目录
```

插件里的命令都通过 `uv run --project <DSFlow 仓库>` 运行，所以要先在 DSFlow 仓库 `uv sync --extra mcp`。
项目级的接入（AGENTS.md、CLAUDE.md、可写登记）仍由 `dsflow attach <目录>` 完成；插件只是让 skill、hook、MCP 不用逐个项目装。

目录：

- `.claude-plugin/plugin.json`：清单。
- `skills/dsflow-project/SKILL.md`：和 `templates/project/.claude/skills/dsflow-project/SKILL.md` 同源（命令前缀以项目 AGENTS.md 为准）。
- `hooks/hooks.json`：PostToolUse · Write|Edit → `dsflow hook guide-lint`。
- `.mcp.json`：`dsflow mcp`（stdio）。
