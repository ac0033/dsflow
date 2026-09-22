---
name: dsflow-project
description: 接入 DSFlow 平台的接口 skill：在一个用 DSFlow 追踪的数据科学项目里，任何时候要推进一步（写计划、执行、写讲解或说明卡、验收、提交审批、等用户确认）都先调用它。它告诉你只用协议里的工具、开工前先检查环境、先调 next、按 tool_calls 做、一步只做一个完整独立的单元、不替用户改状态。
---

# 接入 DSFlow：只按协议做

DSFlow 是本地的数据科学项目全周期追踪平台。**文件是唯一事实来源**：你写进项目目录的每个文件，平台刷新就能看到；你不需要"同步"或"上传"。

## 1. 三种传输，同一套工具

协议 `dsflow protocol`（或工具 `protocol_get`、`GET /api/protocol`）列出全部工具、参数和返回。你手上有哪种传输就用哪种，内容完全一样：

| 你是什么 agent | 用什么 | 怎么调 |
|---|---|---|
| 有 shell（Claude Code、Codex、Cursor 等） | 命令行 | `dsflow call <工具> --args '<json>' -p <项目目录>`（命令前缀以项目 AGENTS.md 第一段为准） |
| 支持 MCP | MCP | 项目里的 `.mcp.json` 或插件已把工具挂好，直接调同名工具 |
| 只有 HTTP | HTTP | `POST http://<平台地址>/api/tools/<工具>`，body 就是参数 JSON |

每次调用返回同一信封：`{"ok": true, "protocol": "1", "data": …}` 或 `{"ok": false, "protocol": "1", "error": {"code", "message", "hint"}}`。`ok` 为 false 就按 `hint` 改，不要绕开。

## 2. 动手之前先调 `next`

`next` 返回项目在哪一步、处于哪个环节（`phase`）、本轮目录缺哪些文件（`missing`）、该做什么（`todo`），以及 **`tool_calls`：下一步该调哪些工具、带什么参数**。按 `tool_calls` 的顺序做，不要自己探索目录结构。返回里还有两样东西：`environment` 是分析环境的快检查（`ready` 为 `false` 就先修环境），`rules` 是下面这两条工作规矩。

表里的「主 agent」「执行 agent」是两个角色，不一定是两个 agent：用户没有另行安排时，你一个人依次担任这两个角色。

| `phase` | 你要做的 |
|---|---|
| `preflight` | 分析环境还没准备好，项目也一步都还没开始：先调 `env_check` 看缺哪一件，再调 `env_prepare` 补齐（命令行：`dsflow attach <项目目录> --venv`），然后再调一次 `next`。环境好了才写第一份计划。 |
| `plan` | 主 agent 用 `file_write` 写 `plan.md`（为什么做、输入、处理办法、产物、验收标准、停止条件），`step_set_status` 改为 `pending_approval`，然后调 `approval_wait`，并**停下来向用户汇报**"计划已提交，等你审批"。不要接着执行。 |
| `await_approval` | 等用户。`approval_wait` 返回 `approved` 就进入执行，`rejected` 就按 `entry.note` 改计划再提交，`pending` 就再调一次。用户在对话里直接表态时，用 `approval_decide` 记录原话（用户说了才能调）。 |
| `execute` | 执行 agent 用 `run_exec` 跑 notebook 或脚本（每次运行都记录，失败也记）；用 `data_register` 登记产出的表（必须同时写 `description`：一行代表什么、怎么来的、后面哪一步会用，每份数据各写各的）；`file_write` 写 `report.md`（用户报告）和 `step_card.yaml`（说明卡）；`guide_init` 生成讲解骨架、`guide_put` 写讲解（自动核对与体检，不通过就改）；`validate`、`check` 都 `ok` 后 `step_set_status` 改为 `awaiting_acceptance`。 |
| `acceptance` | 主 agent 从实际产物独立核对，`file_write` 写 `acceptance.md`；`guide_check`、`guide_lint` 核对讲解；然后 `approval_wait`，停下来向用户汇报结果。 |
| `await_confirmation` | 等用户确认；`confirmed` 之后再调 `next` 进入下一步。 |

## 3. 两条工作规矩

**开工前先检查环境**：接入平台之后、写第一份计划之前，先调 `env_check` 确认分析环境建好了——项目有自己的 `.venv`，平台的 dsflow 挂进了这个环境，pandas 这些后面要用的库能真的 import 进来。`ready` 为 `false` 就先调 `env_prepare`（命令行：`dsflow attach <项目目录> --venv`）把环境补齐，再写计划；计划里要用基础分析库以外的库，在 `env_check` 的 `imports` 里一起确认。环境缺一半时，你要到执行 notebook 那一刻才发现报错，那时计划已经批过、时间已经花掉，只能退回重做。项目一步都还没开始、环境又没准备好时，`next` 返回的 `phase` 就是 `preflight`。

**一步是一个完整独立的单元**：登记步骤和写计划时，一步围绕一个完整的业务目的，它有自己的输入、自己的产物、自己能核对的验收标准，做完能单独讲给用户听。两个问题都答「能」才算一步：这一步的产物能不能被下一步直接使用？验收标准能不能只看本步产物核对？答「不能」就合并或者拆开，拆开之后每一步各自用 `step_add` 登记、各自写计划。把一个阶段的操作全堆在一步里，用户在中间没法评估，出问题要整步重做；把一个操作拆成三步（读文件一步、改列名一步、存盘一步），每一步都没有能交付的产物，审批和验收就空转。

## 4. 其余几条规矩

- **状态只能这样改**：agent 只能把步骤改成 `pending_approval` 和 `awaiting_acceptance`；`in_progress`、`done` 由用户的审批产生。没有审批不执行，没有确认不进下一步。
- **默认主 agent 和执行 agent 是同一个**：同一个 agent 写计划 → 用户批准 → 自己执行 → 自己验收。只有用户明确安排了独立的执行 agent 时才分开，那时主 agent 只写计划与验收，并把本 skill 与已批准的 `plan.md` 交给它。兼任时验收仍要从实际产物重新核对，不复用执行时的中间结果。
- **不写的文件**：`data/raw/`、`lifecycle/steps.json`、`approval_record.md`、历史轮次目录。`file_write` 会拒绝，不要绕过。
- **每句话要能单独看懂**：主语 + 动词 + 具体宾语（表名、列名、文件、术语、数字）+ 结果，以句号结尾；只用 `vocabulary_get` 里有的术语，新术语先 `vocabulary_add`（写明出处）再用。
- **向用户汇报**按 结果与能否继续 → 核心数字 → 主要操作 → 只影响判断的例外 的顺序。

工作方法（计划怎么写、两份报告怎么分工、验收怎么做）见 `data-science-project` skill；没有平台时，那个 skill 也能产出同样的文件结构。
