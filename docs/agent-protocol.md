# DSFlow Agent Protocol（v1）

还没有装好平台的读者先看 [接入指南（五步）](接入指南.md)。任何 agent 接入 DSFlow 都只用本协议里的工具。工具的名字、参数、返回在代码里只定义一次（`dsflow/protocol.py`），本文的「工具」一节、MCP 服务、HTTP 路由、命令行都从那份登记表生成，不会各说各话。机器可读版：`dsflow protocol --format json` 或 `GET /api/protocol` 或工具 `protocol_get`。

## 1. 开工前的工作规矩

这两条规矩在 `dsflow/core/rules.py` 里定义一次，协议文档、`next` 的返回（`rules`）、MCP 服务的 instructions、终端客户端的系统提示、两个 skill 与项目里的 `AGENTS.md` 都从它来；哪个接口漏了，测试会红。

<!-- 由 `dsflow protocol --format markdown` 生成（工作规矩）；不要手改 -->

### 1. 开工前先检查环境

接入平台之后、写第一份计划之前，先调 env_check 确认分析环境建好了：项目有自己的 .venv，平台的 dsflow 挂进了这个环境，pandas 这些后面要用的库能真的 import 进来。

- **为什么**：环境缺一半时，agent 要到执行 notebook 那一刻才发现报错，那时计划已经批过、时间已经花掉，只能退回重做。
- **怎么做**：env_check 返回 ready 为 false 就先调 env_prepare（命令行：dsflow attach <项目目录> --venv）把环境补齐，再写计划；计划里要用基础分析库以外的库，在 env_check 的 imports 里一起确认。

### 2. 一步是一个完整独立的单元

登记步骤和写计划时，一步围绕一个完整的业务目的：它有自己的输入、自己的产物、自己能核对的验收标准，做完能单独讲给用户听。

- **为什么**：把一个阶段的操作全堆在一步里，用户在中间没法评估，出问题要整步重做；把一个操作拆成三步（读文件一步、改列名一步、存盘一步），每一步都没有能交付的产物，审批和验收就空转。
- **怎么做**：两个问题都答「能」才算一步：这一步的产物能不能被下一步直接使用？验收标准能不能只看本步产物核对？答「不能」就合并或者拆开，拆开之后每一步各自用 step_add 登记、各自写计划。

## 2. 三种传输，同一套工具

| 传输 | 目标用户 | 调用方式 |
|---|---|---|
| 命令行 | 能执行 shell 命令的 agent | `dsflow call <工具> --args '<参数 JSON>' -p <项目目录或 id>`；stdout 一行信封 JSON，`ok` 为 false 时退出码 1 |
| MCP | 支持 MCP 的 agent（Claude Code、Codex、Cursor、Claude Desktop…） | 本机 `dsflow mcp`（stdio，`dsflow attach --mcp` 写好 `.mcp.json`）；远程 `http://<平台>:<端口>/mcp`（streamable HTTP；平台用 `--host 0.0.0.0 --token` 启动时请求头带 `Authorization: Bearer <令牌>`） |
| HTTP | 只能发 HTTP 请求的 agent | `POST http://<平台>/api/tools/<工具>`，body 就是参数 JSON，永远 200，看信封的 `ok`；非本机访问带 `Authorization: Bearer <令牌>`（缺令牌 401） |

信封：

```json
{"ok": true,  "protocol": "1", "data": …}
{"ok": false, "protocol": "1", "error": {"code": "not_found|invalid|forbidden|readonly|conflict|io", "message": "…", "hint": "怎么改"}}
```

## 3. 状态机：谁能改什么

```
pending ──agent──▶ pending_approval ──用户通过──▶ in_progress ──agent──▶ awaiting_acceptance ──用户确认──▶ done
                        │ 用户退回：留在 pending_approval                    │ 用户退回：回到 in_progress
```

- agent 只能做两种变化（`step_set_status`）：`pending → pending_approval`（写完 plan.md 提交审批）、`in_progress → awaiting_acceptance`（落盘并通过 validate、check 后提交验收）。
- 用户的通过 / 退回 / 确认由平台按钮或 `approval_decide`（agent 转述用户原话）产生，平台写 `approval_record.md` 并改状态。agent 等审批用 `approval_wait`（长轮询，最长 50 秒，`pending` 就再调）。
- 没有审批不执行，没有确认不进下一步。

## 4. 每步只留这些文件

「主 agent」「执行 agent」是两个角色，不一定是两个 agent：**用户没有另行安排时，同一个 agent 依次担任这两个角色**（自己写计划 → 用户批准 → 自己执行 → 自己验收）；用户明确安排了独立的执行 agent 时才分开。兼任时验收仍要从落盘的产物重新核对，不复用执行时的中间结果。

| 文件 | 谁写 | 什么时候 | 内容 |
|---|---|---|---|
| `plan.md` | 主 agent | 计划 | 为什么做、输入、处理办法、产物、验收标准、停止条件 |
| `approval_record.md` | 平台 / `approval_decide` | 审批与确认 | 不要手写 |
| `nb_<步骤>.ipynb` | 执行 agent | 执行 | 真实执行的 notebook；公共代码 `src/`；每次运行用 `run_exec` |
| `report.md` | 执行 agent 起草，主 agent 审阅 | 执行 | 用户报告，首个标题含步骤编号 |
| `step_card.yaml` | 执行 agent | 执行 | `headline` / `can_continue` / `core_numbers`（带 `source`）/ `artifacts` |
| `guide.yaml` | 执行 agent 起草，主 agent 核对 | 执行 | 讲解，只讲 notebook 单元格；`guide_put` 自动核对与体检 |
| `acceptance.md` | 主 agent | 验收 | 为什么通过或未通过 |

`file_write` 只允许写当前轮次目录和项目根目录的 `src/`；`data/raw/`、`lifecycle/steps.json`、`approval_record.md`、历史轮次一律拒绝。

## 5. 一轮的调用顺序

`next` 的返回里有 `tool_calls`，就是下面这串（agent 不需要自己推）：

0. 接入之后第一次：`next` → `phase: preflight`（项目一步都还没开始、分析环境又没准备好时就是它）：`env_check` → `env_prepare` → 再调一次 `next`。环境准备好了就不出现这个环节；中途环境坏了，`plan` 与 `execute` 两个环节的 `tool_calls` 也会把 `env_check` 排在最前面。
1. `next` → `phase: plan`：`file_write plan.md` → `step_set_status pending_approval` → `approval_wait` →（停下汇报，等用户）
2. `approved` → `phase: execute`：`run_exec` → `data_register` → `file_write report.md / step_card.yaml` → `guide_init` → `guide_put` → `validate` → `check` → `step_set_status awaiting_acceptance`
3. `phase: acceptance`：`guide_check` → `guide_lint` → `file_write acceptance.md` → `approval_wait` →（停下汇报，等用户）
4. `confirmed` → `next` 进入下一步

## 6. 工具

<!-- 由 `dsflow protocol --format markdown` 生成，协议 v1；不要手改 -->

### 协议

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `protocol_get` | 本协议的机器可读版：状态机、文件契约、全部工具及参数。 | 无 | `协议文档` |

### 项目

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `projects_list` | 平台里登记的项目。 | 无 | `[{id, name, root, readonly, step_count}]` |

### 环境

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `env_check` | 开工前的环境自检：项目有没有自己的 .venv、平台的 dsflow 挂没挂进去、要用的库能不能真的 import 进来。接入之后、写第一份计划之前先调它；ready 为 false 就先修环境再开始，不要带着报错执行。 | `project`：项目 id 或目录、`imports`（可选）：基础分析库以外还要确认能 import 的库名（计划里要用什么就写什么） | `{ready, python, checks: [{name, status, detail, fix}], fix}` |
| `env_prepare` | 准备分析环境：在项目里建 .venv、装基础分析库（pandas、matplotlib、scikit-learn、openpyxl）、把平台的 dsflow 挂进去，装完再自检一遍。第一次要联网下载，可能要几分钟；只读接入的项目不做。 | `project`：项目 id 或目录、`libs`（可选）：除基础分析库以外还要装的库名 | `{ready, log, checks}` |

### 进度

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `next` | 项目在哪一步、处于哪个环节、本轮目录缺什么文件、该做什么；tool_calls 是下一步该调的工具。environment 是分析环境的快检查，rules 是每个环节都要守的工作规矩。 | `project`：项目 id 或目录、`step`（可选）：只看某一步（默认取顺序最靠前的进行中步骤） | `{step, phase, files, missing, todo, commands, tool_calls, issues, attention, approvals, environment, rules}` |
| `steps_list` | 全部步骤：编号、标题、阶段、状态、当前轮次、目录。 | `project`：项目 id 或目录 | `[{id, title, stage, order, status, status_label, revision, dir}]` |
| `step_add` | 在注册表里登记一个新步骤（状态 pending）：编号、阶段、标题、目录（默认 steps/<阶段目录>/<编号>_<标题>）、依赖的步骤。新项目提出阶段划分后用它把步骤一个个登记进来。一步是一个完整独立的单元：有自己的输入、产物和能核对的验收标准；不要把一个阶段的操作堆成一步，也不要把一个操作拆成三步。 | `project`：项目 id 或目录、`step`：步骤编号，如 1.1、`stage`：阶段序号（见 dsflow.yaml / 注册表 stages）、`title`：标题、`dir`（可选）：目录（相对项目根，可省略）、`depends_on`（可选）：依赖的步骤编号（显式登记，不按编号推导）、`op`（可选）：这一步的目的（一句话） | `{id, dir, stage}` |
| `step_get` | 一步的详情：轮次、本轮文件（按角色）、说明卡、验收报告、依赖。 | `project`：项目 id 或目录、`step`：步骤编号 | `step_detail` |

### 文件

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `file_read` | 读项目里的一个文本文件（相对项目根目录）。 | `project`：项目 id 或目录、`path`：相对路径 | `{path, size, suffix, content}` |
| `file_write` | 写项目里的文件。只允许写当前轮次目录（及项目根目录的 src/）；不能写 data/raw、注册表、审批记录、历史轮次。写 guide.yaml 会顺带体检。 | `project`：项目 id 或目录、`path`：相对路径、`content`：全文、`append`（可选）：true 时追加而不是覆盖 | `{path, bytes, lint?}` |

### 状态

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `step_set_status` | agent 能做的两种状态变化：pending → pending_approval（提交审批）、in_progress → awaiting_acceptance（提交验收）。其余由用户审批产生。 | `project`：项目 id 或目录、`step`：步骤编号、`status`：pending_approval 或 awaiting_acceptance | `{step, from, to}` |

### 运行

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `run_exec` | 在平台所在机器上执行项目内的 notebook（走 dsflow 的 notebook 执行器）或脚本，并记录为一次运行。只能执行项目目录内的文件。超时未结束就返回 running，用 run_get 追踪。 | `project`：项目 id 或目录、`step`：步骤编号、`target`：notebook 或脚本的相对路径、`hypothesis`（可选）：这次运行要验证什么、`params`（可选）：notebook 参数（名 → 值）、`timeout`（可选）：最多等多少秒（默认 600） | `{run_id, status, exit_code, duration_s, log_tail}` |
| `run_get` | 一次运行的状态、指标、结论和日志尾部。 | `project`：项目 id 或目录、`run_id`：运行编号 | `{run_id, status, …, log_tail}` |
| `runs_list` | 最近的运行记录。 | `project`：项目 id 或目录、`step`（可选）：只看某一步、`limit`（可选）：最多几条 | `[{run_id, step, status, started_at, hypothesis, conclusion, validity}]` |

### 数据

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `data_register` | 登记一个数据集版本（只记路径与哈希）。产出的表写清上游、产出步骤；替代旧表就写 replaces。 | `project`：项目 id 或目录、`path`：文件相对路径、`name`：数据集名（用数据表里的说法）、`stage`（可选）：raw / processed / features / splits / model_input / predictions / other、`parents`（可选）：上游数据集名、`produced_by`（可选）：产出它的步骤、`description`（可选）：一句话介绍这份数据：一行代表什么、怎么来的、后面哪一步会用；每份数据各写各的、`replaces`（可选）：它登记后不再有用的数据集名 | `{version, created}` |
| `data_describe` | 补写或改写一份数据的介绍（数据里文件名下面那行小字），不必重新登记。 | `project`：项目 id 或目录、`name`：数据集名、`description`：一句话介绍这份数据：一行代表什么、怎么来的、后面哪一步会用；每份数据各写各的 | `{name, description}` |
| `data_link` | 把一张只读没改的表挂到某一步（核对 / 读取），数据层才能显示这一步碰了它。 | `project`：项目 id 或目录、`name`：数据集名、`step`：步骤编号、`role`（可选）：核对 或 读取 | `{name, step, role}` |
| `data_replace` | 声明替代关系：新表登记后旧表退出「后存量」。 | `project`：项目 id 或目录、`name`：新表名、`old`：被替代的表名 | `{name, replaces}` |
| `data_list` | 数据集演变链：每个数据集的版本、产出步骤、替代关系。 | `project`：项目 id 或目录 | `[dataset]` |
| `data_peek` | 看一份数据文件的前几行（最多 20 行、8 列），并给出这张表的全部列名。只读前几行，不整表转换，大文件也很快。 | `project`：项目 id 或目录、`path`：数据文件相对路径、`columns`（可选）：只看这几列（逗号分隔；留空取前 8 列）、`limit`（可选）：看几行（最多 20）、`sheet`（可选）：xlsx 的第几个工作表（从 0 数） | `{path, format, columns, rows, all_columns, total_columns, size}` |
| `data_query` | 对一份数据文件跑一条只读 SQL：数一数、分组汇总、挑几行来看。表名固定写 data，只能 SELECT / WITH（不能改任何东西）。文件要先转成 Parquet（在网页的数据页打开过一次就有），没转的先用 data_peek。 | `project`：项目 id 或目录、`path`：数据文件相对路径、`sql`：一条查询语句，表名写 data，例如 SELECT 类目, count(*) AS 行数 FROM data GROUP BY 1 ORDER BY 2 DESC、`limit`（可选）：最多返回多少行（默认 50，上限 200） | `{columns, rows, truncated}` |

### 模型

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `model_register` | 登记模型文件为候选版本（不覆盖已登记的文件）。 | `project`：项目 id 或目录、`path`：模型文件相对路径、`name`：模型名、`run_id`（可选）：产出它的运行编号、`description`（可选）：一句话说明 | `{name, version}` |

### 讲解

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `guide_init` | 按 notebook 真实单元格生成 guide.yaml 骨架并写到本轮目录（已有就不覆盖，返回现有内容）。 | `project`：项目 id 或目录、`step`：步骤编号、`rev`（可选）：轮次、`notebook`（可选）：本轮有多个 notebook 时指定一个 | `{path, text, existed}` |
| `guide_get` | 读一步的讲解：内容、可讲的 notebook、引用与数字的核对结果、术语。 | `project`：项目 id 或目录、`step`：步骤编号、`rev`（可选）：轮次 | `guide_view` |
| `guide_check` | 核对讲解：引用的 notebook、单元格、行号存不存在，写的数字能不能在输出里找到。 | `project`：项目 id 或目录、`step`：步骤编号、`rev`（可选）：轮次 | `{errors, checked, found, missing}` |
| `guide_lint` | 体检讲解：用词、句子、篇幅、照搬。空列表就是通过。 | `project`：项目 id 或目录、`step`（可选）：只看某一步 | `[{step, revision, issues}]` |
| `guide_put` | 写入 guide.yaml 全文，并立刻核对（引用、数字）与体检（用词、句子、篇幅）。 | `project`：项目 id 或目录、`step`：步骤编号、`text`：guide.yaml 全文、`rev`（可选）：轮次 | `{path, checks, lint}` |

### 术语

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `vocabulary_get` | 项目术语表（项目自带的 + 平台目录里的）。 | `project`：项目 id 或目录 | `[{term, meaning, source, aliases, avoid}]` |
| `vocabulary_add` | 登记一个术语（写明出处）；avoid 里的说法以后会被体检拦下。已有同名术语就更新。 | `project`：项目 id 或目录、`term`：术语、`meaning`：白话解释、`source`（可选）：出处：数据表字段、表名或既有对话、`aliases`（可选）：别名、`avoid`（可选）：不许再用的说法 | `{term, path}` |

### 待决

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `decisions_list` | 需要用户裁定的问题（平台记录的 + 项目文件里 decisions_required.json 的）。 | `project`：项目 id 或目录 | `[pending]` |
| `decisions_add` | 记一个需要用户裁定的问题（不替用户裁定）。 | `project`：项目 id 或目录、`question`：问题、`recommendation`（可选）：推荐答案、`basis`（可选）：依据、`alternatives`（可选）：备选差异、`impact`（可选）：影响范围、`blocking`（可选）：是否阻塞后续执行、`step`（可选）：关联步骤 | `pending` |

### 核对

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `validate` | 注册表校验；errors 为空才算通过。 | `project`：项目 id 或目录 | `{ok, steps, issues}` |
| `check` | 交接前核对：告警 + 说明卡数字回产物重算 + 术语检查（同 dsflow check）。 | `project`：项目 id 或目录、`step`（可选）：只看某一步 | `{ok, alerts, steps}` |

### 审批

| 工具 | 做什么 | 参数 | 返回 |
|---|---|---|---|
| `approval_get` | 一步的审批记录，以及现在等的是计划审批还是完成确认。 | `project`：项目 id 或目录、`step`：步骤编号 | `{status, pending, entries}` |
| `approval_decide` | 记录用户在对话里的审批（用户说了才能调）：decision 为 approve / reject；kind 省略时按当前状态判定。平台会改状态并写审批记录。 | `project`：项目 id 或目录、`step`：步骤编号、`decision`：approve / reject、`note`（可选）：用户原话、`kind`（可选）：approval / acceptance | `{from, to, record, entry, warnings}` |
| `approval_withdraw` | 撤回这一步最后一条审批（用户说填错了才能调）：状态改回表态之前，审批记录里追加一条「撤回」，记录从不删除。只能撤最后一条，且状态还停在那条记录留下的状态。 | `project`：项目 id 或目录、`step`：步骤编号、`note`（可选）：用户原话：为什么撤回 | `{from, to, record, entry, withdrew}` |
| `approval_wait` | 等用户在平台审批或确认：最多等 timeout 秒（上限 50，适合长轮询），到时未决返回 result=pending，再调一次即可。 | `project`：项目 id 或目录、`step`：步骤编号、`timeout`（可选）：最多等多少秒（≤ 50） | `{result: approved|confirmed|rejected|pending, status, entry}` |
