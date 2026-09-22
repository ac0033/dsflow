# AGENTS.md（DSFlow 被管项目）

本项目用 DSFlow 追踪：**文件是唯一事实来源**，平台只读取、核对、展示，你写完文件切回浏览器就是最新状态。接入按 **DSFlow Agent Protocol**（`__DSFLOW__ protocol`，或工具 `protocol_get`）：一套工具，三种传输。在本目录里运行 dsflow 命令用：`__DSFLOW__ <子命令>`。

**动手之前先看进度**：`__DSFLOW__ next . --json`（或工具 `next`）。它告诉你在哪一步、处于哪个环节、本轮目录缺哪些文件、该做什么，`tool_calls` 就是下一步该调的工具和参数——照它做，不要自己探索目录。返回里的 `environment` 是分析环境的快检查，`rules` 是下面那两条工作规矩；环境没准备好、项目又一步都没开始时，`phase` 就是 `preflight`。

## 开工前的两条工作规矩

- **开工前先检查环境**：接入平台之后、写第一份计划之前，先调 `env_check`（命令行：`__DSFLOW__ call env_check -p .`）确认分析环境建好了——项目有自己的 `.venv`，平台的 dsflow 挂进了这个环境，pandas 这些后面要用的库能真的 import 进来。`ready` 为 `false` 就先调 `env_prepare`（命令行：`__DSFLOW__ attach . --venv`）补齐再写计划；计划里要用基础分析库以外的库，在 `env_check` 的 `imports` 里一起确认。环境缺一半时，你要到执行 notebook 那一刻才发现报错，那时计划已经批过，只能退回重做。
- **一步是一个完整独立的单元**：登记步骤和写计划时，一步围绕一个完整的业务目的，它有自己的输入、自己的产物、自己能核对的验收标准。两个问题都答「能」才算一步：这一步的产物能不能被下一步直接使用？验收标准能不能只看本步产物核对？答「不能」就合并或者拆开，拆开之后每一步各自用 `step_add` 登记、各自写计划。不要把一个阶段的操作堆成一步，也不要把一个操作拆成三步（读文件一步、改列名一步、存盘一步）。

## 一轮的五个环节（每个步骤、每一轮都一样）

下表的「主 agent」「执行 agent」是两个角色，不一定是两个 agent：**用户没有另行安排时，同一个 agent 依次担任这两个角色**（自己写计划 → 用户批准 → 自己执行 → 自己验收）。用户明确安排了独立的执行 agent 时才分开。

| 环节 | 谁 | 落哪些文件 | 状态（`lifecycle/steps.json`） |
|---|---|---|---|
| 1 制定计划 | 主 agent | `plan.md`：为什么做、输入、处理办法、产物、验收标准、停止条件 | agent 改为 `pending_approval`（工具 `step_set_status`） |
| 2 用户评估 | 用户 | `approval_record.md`（平台写，不要手写） | 平台改为 `in_progress` |
| 3 执行 | 执行 agent | `nb_<步骤>.ipynb`（公共代码放 `src/`）、每次运行用 `run_exec` 记录、`report.md`（用户报告）、`step_card.yaml`（说明卡）、`guide.yaml`（讲解初稿） | agent 在 `validate`、`check` 通过后改为 `awaiting_acceptance` |
| 4 验收 | 主 agent | `acceptance.md`：从实际产物独立核对，说明为什么通过或未通过；跑 `guide_check`、`guide_lint` | 不变 |
| 5 用户确认 | 用户 | `approval_record.md` 再追加一条 | 平台改为 `done`（退回则 `in_progress`） |

- **等审批**：交完计划（或验收报告）后调 `approval_wait`（命令行：`__DSFLOW__ await . <步骤> --timeout 7200`，能后台运行的 agent 放后台，命令退出即被唤醒），然后停下来向用户汇报。用户在对话里表态时，调 `approval_decide`（命令行：`__DSFLOW__ approve / reject / confirm . <步骤> --note "<原话>"`）记录，平台改状态。
- 没有审批不执行；没有用户确认不改为 `done`、不进入下一步。兼任两个角色时验收仍要从实际产物重新核对，不复用执行时的中间结果；用户明确安排了独立的执行 agent 时，主 agent 只写计划与验收。
- 改 `lifecycle/steps.json` 只走 `step_set_status`；直接改文件前必须重新读取（平台可能刚改过状态）。
- 每步只留上面这些文件；`plan_user.md`、`plan_original.md`、`report_rewrite.md` 这类自用文件不要产生。
- 返工开新轮次 `revisions/rNN_日期_说明/`，在 `revisions[].summary` 写明相对上一轮递进了什么；历史不覆盖。**只是替代 / 覆盖上一轮的内容，就更新原轮次，不新增。**

## 代码在哪个 Python 里跑

本项目的代码跑在项目自己的虚拟环境 `.venv` 里（`__DSFLOW__ init` 建的，`__DSFLOW__ attach . --venv` 可以补建）。`run_exec` 会自动用它，你不用指定解释器。里面装了 pandas、matplotlib、scikit-learn、openpyxl，平台的 dsflow 也挂在其中，所以 notebook 里能直接 `import dsflow` 记录运行。

- 缺库时在项目目录里运行 `uv pip install <库名>` 装进这个 `.venv`（没有 uv 就用 `.venv/Scripts/python -m pip install <库名>`），并在 `plan.md` 或 `report.md` 里写明为什么要它。
- 报 `No module named 'pandas'` 说明 `.venv` 没建成，报 `No module named 'dsflow'` 说明 dsflow 没挂进去，两种都用 `__DSFLOW__ attach . --venv` 修，`__DSFLOW__ doctor .` 能看出是哪一种。开工前调一次 `env_check` 就能提前发现这两种情况。
- 不要在 `.venv` 里装与本项目无关的包，也不要把 `.venv` 提交进版本库。

## 三份要写给人看的文件

- **`report.md` 用户报告**：写给不看代码的读者。开头一句说做完了吗、最重要的业务结果、能否继续；正文按读者要弄明白的一到三个问题组织，每个问题走 输入 → 关键操作 → 实际输出 → 业务上意味着什么；至少给一个真实可核对的例子。
- **`guide.yaml` 讲解**：写给懂业务、能读代码、没做过数据科学的负责人。只讲 notebook 里真实的单元格（做什么 / 为什么 / 输出结果讲解），不复述用户报告。开头六段 背景 / 目的 / 结论 / 操作 / 结果 / 下一步各一句；结论最多一个数字，结果写这一步留下的核心产出。执行 agent 起草，主 agent 验收时核对。用 `guide_init` 生成骨架、`guide_put` 写入（自动核对引用与数字、体检用词与篇幅；本项目 `.claude/settings.json` 的 hook 也会在你改 guide.yaml 时自动体检）。
- **`step_card.yaml` 说明卡**：只有四样——`headline` 一句话结论、`can_continue`、`core_numbers`（每个写 `source`，平台从产物重算核对）、`artifacts`（能出图就登记 `kind: figure`）。

## 每句话都要能单独看懂

主语 + 动词 + 具体宾语（表名、列名、文件、术语、数字）+ 结果，以句号结尾。不用口语缩略动词（对上、合上、钉死、站住、跑通……），抽象词（口径、主线……）没在术语表登记就不用。**不造新概念**：只用 `vocabulary.json` 登记过、或数据表字段里有的说法；新术语先 `vocabulary_add`（写明出处）再用，同一个东西始终用同一个说法。

## 汇报规则

首屏只回答四件事：做完了吗、能否继续；核心数字（处理前 / 变化 / 处理后，写清是记录数还是不同值个数、期间、范围）；用直白的话说主要操作；只列会影响判断的例外。其余放在后面。必须写明产物路径。

## 登记数据与模型

- 产物只算有用的最终文件：后续要用的表、给业务看的报告和图、模型。产出的表用 `data_register`（或 SDK `run.log_output`）登记，旧表被替代时写 `replaces`；中间结果和核对清单不登记。
- **登记时必须写 `description`**：它是这份数据的简要介绍——一行代表什么、怎么来的、后面哪一步会用；数据里文件名下面那行小字就是它。每份数据各写各的，不要几份共用一句话；漏写登记不进来，事后补写用 `data_describe`。
- 只读没改的表：走 `run_exec` 的步骤自动记录；否则 `data_link`。
- 模型：`model_register`（或训练脚本里 `run.log_model`），登记为候选；不覆盖已登记的模型文件。

## 不要做的事

- 不修改 `data/raw/`（原始数据只读，平台会告警）；不删除运行记录。
- 不替用户审批计划、裁定待决事项、把步骤改为 `done`、把模型标为已验收 / 已交付。
- 依赖要在 `steps.json` 显式登记，不按编号推导；不在历史轮次上直接改。

## 常用命令（命令行传输；MCP 用同名工具）

```
__DSFLOW__ call env_check -p .                        # 开工前的环境自检：.venv、平台的 dsflow、要用的库
__DSFLOW__ next . --json                              # 在哪一步、缺什么、下一步做什么（tool_calls）
__DSFLOW__ call <工具> --args '<json>' -p .            # 按协议调任何工具；工具清单：__DSFLOW__ protocol
__DSFLOW__ await . <步骤> --timeout 7200               # 等用户在平台审批 / 确认（退出码 0 通过、3 退回、4 超时）
__DSFLOW__ approve . <步骤> --note "<原话>"             # 用户在对话里通过了；reject 退回；confirm 确认完成
__DSFLOW__ validate .                                 # 注册表校验
__DSFLOW__ check . --step <步骤>                      # 交接前核对：告警 + 数字核对 + 术语检查
__DSFLOW__ run <步骤> -p . -- python -m dsflow.tracking.notebook <本轮目录>/nb_<步骤>.ipynb
__DSFLOW__ guide init . <步骤>                        # 讲解骨架；guide check / guide lint 核对与体检
```
