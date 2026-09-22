# 参与贡献

感谢你愿意花时间。DSFlow 目前处于公开预览：代码与功能公开，可在本机安装试用；多用户登录与服务器部署尚未完成。欢迎 issue、讨论和 PR，下面是几条能让贡献顺利合入的约定。

## 开发环境

前置条件与 [接入指南 1.2](docs/接入指南.md#12-前置条件) 相同：uv、Git、Node.js 20 或更新。

```bash
git clone https://github.com/ac0033/dsflow.git && cd dsflow
npm --prefix web install && npm --prefix web run build   # 网页（含 tsc 类型检查；用 pnpm 也行）
uv sync --all-extras --dev                               # Python 依赖，含 mcp、chat 两组可选依赖与测试工具
uv run pytest -m "not slow" -q                           # 测试（不需要网络与模型密钥）
uv run pytest -q                                         # 含 slow：会联网装库
uv run ruff check .                                      # lint
uv run dsflow ui --dev                                   # 前端热更新模式，平台目录是 <仓库>/.dsflow_home
```

提 PR 前请确保 `uv run pytest -m "not slow" -q` 全绿、`uv run ruff check .` 干净；CI 会在 Ubuntu 与 Windows 上再跑一遍。

## 改代码时

- **规矩只写一处**：agent 的工作规矩定义在 `dsflow/core/rules.py`，协议文档、`next` 的返回、MCP、终端客户端、两个 skill 与 `AGENTS.md` 模板都从它来，`tests/test_rules.py` 逐个文件核对。改规矩就改那一处，再跑测试看哪些文件要同步。
- **协议工具改动要同步三处**：`dsflow/protocol.py` 的登记表是源；`docs/agent-protocol.md` 由 `uv run dsflow protocol --format markdown` 生成；`skills/dsflow-project/SKILL.md` 是接口 skill 的源，`plugin/skills/` 与 `templates/project/.claude/skills/` 里的两份副本必须逐字一致（`tests/test_mcp.py` 核对）。
- **版本号三处一致**：`pyproject.toml`、`dsflow/__init__.py`、`web/package.json`（`tests/test_public_hygiene.py` 核对），插件 `plugin/.claude-plugin/plugin.json` 跟随。
- **数据契约**：改了 `dsflow/core/schemas.py` 或 `dsflow/delivery/models.py` 的字段，运行 `uv run dsflow schema` 重新生成 `docs/contracts/`。
- **讲解与文档的用词**：讲解文本按 [docs/讲解写法.md](docs/讲解写法.md) 写，`dsflow guide lint` 会机械检查；面向用户的文档假设读者没有技术基础，命令写清在哪运行、运行完应该看到什么。
- **界面文字**不出现底层文件名（例如注册表、`approval_record.md`），说人话。
- **不把本机信息写进仓库**：绝对路径、私人项目名、邮箱、密钥都不进代码、文档与测试；`tests/test_public_hygiene.py` 会拦。开发者自己的方案、笔记放在仓库内的 `.notes/`（已 gitignore）。

## 发布一个版本

1. 三处版本号升到新版本，`docs/CHANGELOG.md` 顶部新增该版本的条目。
2. 本地 `uv run pytest -m "not slow" -q` 与 `npm --prefix web run build` 通过。
3. 提交后打标签并推送：`git tag vX.Y.Z && git push origin main vX.Y.Z`。`release.yml` 会构建 wheel、从 CHANGELOG 截取该版本的说明并创建 pre-release（1.0 之前都标 pre-release）。

## 提 issue 时最有用的信息

- 装法（① uv tool / ② venv + pip / ③ wheel / ④ 仓库内）与操作系统；`dsflow doctor` 的输出。
- 接入方式（MCP / 命令行 / HTTP / `dsflow chat`）与所用 agent。
- 相关命令或工具的返回（`dsflow next --json`、协议信封里的 `error`）。
- 能复现的最小项目结构。请先脱敏，不要贴密钥或真实业务数据。

## 许可

提交的贡献按仓库的 [MIT 许可](LICENSE) 发布。
