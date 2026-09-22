# DSFlow Agent 指南

> 接入的标准是 [DSFlow Agent Protocol](agent-protocol.md)（一套工具、三种传输）；本文是背景与写法说明，命令行子命令与协议工具一一对应。

给在被管项目里工作的 agent（主 agent 与执行 agent 两个角色，默认由同一个 agent 兼任）：怎样登记数据与运行、写说明卡、更新状态、记录待决事项、登记模型与交付，让平台能追踪和核对。

项目里放一份 `AGENTS.md`（`dsflow init` 会从 `templates/project/AGENTS.md` 复制），里面是精简规则；本文是完整说明。可运行的完整例子见 `examples/demo_project/`（`uv run python examples/demo_project/scripts/run_all.py`）。

## 0. 接入与一轮的顺序

**接入一次**：`uv run dsflow init <目录> --name 项目名`（新项目）或在已有项目上 `uv run dsflow attach <目录>`。它装好 `AGENTS.md`（跨 agent 的工作规则，任何 agent 先读它）、`CLAUDE.md`（一行 `@AGENTS.md`，Claude Code 只读它）、`.claude/skills/dsflow-project/SKILL.md`（Claude Code 在项目里自动发现的 skill）、`.claude/settings.json` 里的讲解体检 hook，并把项目登记为可写。之后你只需在项目目录里正常和 agent 对话，agent 落盘的每个文件平台都立刻读到。

**开工前先检查环境**：接入之后、写第一份计划之前，先调 `env_check`（命令行 `dsflow call env_check -p <目录>`）确认分析环境建好了——项目有自己的 `.venv`，平台的 dsflow 挂进了这个环境，pandas 这些后面要用的库能真的 import 进来。`ready` 为 `false` 就先调 `env_prepare`（命令行 `dsflow attach <目录> --venv`）补齐，再写计划；计划里要用基础分析库以外的库，在 `env_check` 的 `imports` 里一起确认。项目一步都还没开始、环境又没准备好时，`next` 返回的环节就是 `preflight`。环境缺一半时，agent 要到执行 notebook 那一刻才发现报错，那时计划已经批过、时间已经花掉，只能退回重做。

**一步是一个完整独立的单元**：登记步骤和写计划时，一步围绕一个完整的业务目的，它有自己的输入、自己的产物、自己能核对的验收标准。两个问题都答「能」才算一步：这一步的产物能不能被下一步直接使用？验收标准能不能只看本步产物核对？答「不能」就合并或者拆开，拆开之后每一步各自用 `step_add` 登记、各自写计划。不要把一个阶段的操作堆成一步，也不要把一个操作拆成三步（读文件一步、改列名一步、存盘一步）。这两条规矩在 `dsflow/core/rules.py` 里定义一次，协议文档、`next` 的返回、MCP、终端客户端、两个 skill、项目里的 `AGENTS.md` 都从它来。

**动手之前先 `dsflow next . --json`**：它告诉 agent 项目在哪一步、处于哪个环节、本轮目录缺哪些文件、该跑哪条命令；返回里的 `environment` 是分析环境的快检查，`rules` 是上面那两条工作规矩。

| 环节 | 谁 | 落哪些文件 | 注册表状态 |
|---|---|---|---|
| 1 制定计划 | 主 agent | `plan.md` | 主 agent 改为 `pending_approval` |
| 2 用户评估 | 用户 | `approval_record.md`（由平台或 `dsflow approve` 写） | 平台改为 `in_progress` |
| 3 执行 | 执行 agent | `nb_<步骤>.ipynb`、运行记录（`dsflow run`）、`report.md`、`step_card.yaml`、`guide.yaml` 初稿 | 执行 agent 在 `validate`、`check` 通过后改为 `awaiting_acceptance` |
| 4 验收 | 主 agent | `acceptance.md`（或 `acceptance/<日期>_<说明>/report.md`）；跑 `guide check`、`guide lint` 核对讲解 | 不变 |
| 5 用户确认 | 用户 | `approval_record.md` 再追加一条 | 平台改为 `done` |

没有审批不执行；没有用户确认不改为 `done`、不进入下一步。表里的两个角色默认由同一个 agent 兼任（自己写计划 → 用户批准 → 自己执行 → 自己验收），用户明确安排了独立的执行 agent 时才分开；兼任时验收仍要从实际产物重新核对，不复用执行时的中间结果。改 `steps.json` 之前必须重新读文件（平台可能刚改过状态）。每步只留上面这些文件；`plan_user.md` 平台仍认识，但不再要求。

**审批怎样传回 agent**：平台不能把消息推进正在运行的 agent 会话，所以反过来由 agent 等文件——主 agent 交完计划后运行 `dsflow await . <步骤> --timeout 7200`（Claude Code 用 Bash 的后台方式，命令退出即被唤醒），用户在步骤页头的审批条点「通过 / 退回 / 确认完成」，平台把原话追加进 `approval_record.md`、改注册表状态，`await` 随即退出（退出码 0 通过或确认、3 退回、4 超时），stdout 是一行 JSON，`entry.note` 就是用户原话。用户在对话里表态时，主 agent 运行 `dsflow approve / reject / confirm . <步骤> --note "<原话>"`，走同一段代码。

**表错了可以撤回**：审批条上有「撤回这条」（步骤已经不在待审批 / 待验收时，标题下面那行细条上也有），或者运行 `dsflow withdraw . <步骤> --note "<为什么撤>"`、调协议工具 `approval_withdraw`。撤回把步骤状态改回表态之前，并在 `approval_record.md` 里**追加**一条「撤回」——记录从不删除，撤了什么、为什么撤都留着。两条限制：只能撤最后一条；这一步的状态还得停在那条记录留下的状态，已经接着往下做了就撤不动，这时在对话里和 agent 说。agent 正在 `await` 时，最后一条是撤回就当作还没表态，继续等。

`approval_record.md` 的格式固定、可解析，平台和命令行都这样写：

```
# 审批记录 · 1.2 订单清洗

## 2026-09-17 15:20 · 通过 · 计划审批（平台）
**原话**：可以，按这个做。

- 状态：pending_approval → in_progress
- 依据：plan.md（修改于 2026-09-17 14:58）
```

平台改注册表只在这一处（`dsflow/core/approval.py`），三道护栏：只读项目一律拒绝（403）；当前状态必须是转换起点（409），批准计划时 `plan.md` 必须存在，确认完成时没有验收报告只警告不拦；写之前重新读文件、校验预检、临时文件加原子替换。

## 1. 文件与分工

文件是唯一事实来源，平台只读取、核对、展示（可写项目里平台只写 `.dsflow/` 和交付清单）。

| 文件 | 谁写 | 平台做什么 |
|---|---|---|
| `lifecycle/steps.json` | agent | 校验、流程图、看板 |
| `steps/…/plan.md`、`approval_record.md` | agent / 平台 | 执行层「执行计划」展示 |
| `steps/…/step_card.yaml` | agent | 首屏展示；**数字核对**、**术语检查** |
| `steps/…/guide.yaml`（讲解） | 执行 agent 起草，主 agent 核对 | 步骤页默认打开的「讲解」与看板思维导图；数字核对、体检 |
| `steps/…/report.md`（用户报告）、`acceptance.md`（验收报告） | 执行 agent / 主 agent | 执行层「产物」里列出，可打开 |
| `steps/…/outputs/…` | 代码 | 数据浏览、画像、版本对比 |
| `.dsflow/runs/<id>/run.json` | SDK / `dsflow run` | 运行与实验、复现卡片、停止规则 |
| `.dsflow/models/<名>.json` | SDK / `dsflow model` | 模型登记与状态门槛 |
| `delivery/<模型名>/checklist.yaml` | 平台生成事实部分，agent 补判断部分 | 交付清单核对 |
| `vocabulary.json` | agent | 术语检查 |
| `decisions_required.json` | agent | 看板与"问题与决策"只读显示 |

只读接入的项目（例如已有的项目导入平台）：平台的一切状态写在平台目录，项目目录不落任何文件。

## 2. 注册表：步骤、轮次、状态

`lifecycle/steps.json` 的每个步骤：

```json
{
  "id": "1.2", "stage": 1, "order": 2, "title": "订单清洗",
  "dir": "steps/01_数据预处理/1.2_订单清洗",
  "status": "awaiting_acceptance",
  "op": "这一步的目的", "finding": "一句话结论", "decision": "据此做了什么决定",
  "execution_notebooks": ["steps/01_数据预处理/1.2_订单清洗/nb_1.2.ipynb"],
  "current_revision": "r01", "revisions": []
}
```

- **状态**：`pending` 未开始 → `pending_approval` 待审批 → `in_progress` 进行中 → `awaiting_acceptance` 待验收 → `done` 已完成 / `partial` 部分完成 / `stopped` 已停止。
- `in_progress`、`awaiting_acceptance` 必须有 `plan.md`；`done`、`partial` 还要有 `report.md`（首个标题含步骤编号），以及真实执行的 notebook（默认 `nb_X.Y.ipynb`）——**用脚本执行时登记 `execution_scripts` 代替 notebook**，真实执行的证据是平台里的运行记录。
- **依赖**要在 `dependencies` 显式登记（`from`、`to`、`label` 写明传递的是什么），不按编号推导。跳回更早的步骤登记 `back_edges`。
- **轮次怎么划分**：新轮次必须是在上一轮基础上**递进或优化**（或者执行到后面的阶段倒回来优化、试新方向），目录 `revisions/rNN_日期_说明/`（里面有自己的 `plan.md`），在 `revisions` 登记并在 `summary` 写明相对上一轮改了什么，在 `revision_loops` 写明为什么返工；历史轮次不覆盖。**如果只是替代或覆盖上一轮的内容，就更新原轮次，不新增轮次。** r02 起没写 `summary` 的轮次，看板会标出来。
- 改完运行 `uv run dsflow validate .`。

## 3. 登记数据

原始数据只读。平台只记录路径与 SHA256，不复制数据；原始文件被改动时看板会给出**严重**告警。

```
uv run dsflow data add . data/raw/orders.csv --name orders_raw --stage raw --description "一行 = 一个订单行，按采购系统导出，1.2 清洗后进主数据"
```

**`--description` 是这份数据的简要介绍**：数据标签页里，文件名下面那行小字就是它。行列数、版本、产出步骤平台自己会显示，这一句要补平台看不出来的三件事——这份文件装的是什么（一行代表什么）、它是怎么来的（来自哪个工作表 / 哪一步、做过什么处理）、后面哪一步会用它。**每份数据各写各的**：几份数据共用同一句话，读的人就分不清它们的差别，平台会把没写介绍和雷同介绍都报成告警。已经登记过的表事后补写：

```
uv run dsflow data describe . orders_raw "一行 = 一个订单行，按采购系统导出，1.2 清洗后进主数据"
```

也可以在 `dsflow.yaml` 的 `datasets` 里声明，再 `uv run dsflow data sync .`。代码里的输入输出用 SDK 登记（见下节），会自动建立血缘。

**替代关系（`--replaces`）**：一张新表登记后，如果旧表就不再是后续要用的最终文件（清洗后的表替代原始表、整理后的商品列表替代两份导出），要声明出来，旧表才会从数据层的「后存量」退出：

```
uv run dsflow data add . data/processed/orders_clean.parquet --name orders_clean --stage processed --parent orders_raw --produced-by 1.2 --replaces orders_raw --description "一行 = 一个订单行，1.2 去掉空标题和重复行后得到，后续步骤都读它"
uv run dsflow data replace . 商品列表_整理后 --old 商品列表_2024_2025 --old 商品列表_2026   # 已登记的表事后补声明
```

SDK 里是 `run.log_output(df, name="orders_clean", path=…, description="一行 = 一个订单行，1.2 清洗后得到", replaces=["orders_raw"])`。

## 4. 记录运行

**每次尝试都要记，无论结果好坏。** 无效、无结论、失败的尝试会进入"探索记录"，避免重复踩坑。

```python
import dsflow

with dsflow.start_run("7.1", hypothesis="加入近 6 月均值后，验证期 MAE 低于最好的基线") as run:
    run.log_input("steps/04_特征工程/4.1_月度特征/outputs/features.parquet", name="features")
    run.log_params({"特征": ["lag1", "lag2", "lag3", "mean6"]})
    run.log_metrics({"MAE_验证": mae_valid})
    for month, value in mae_by_month.items():
        run.log_metrics({"MAE_验证": value}, fold=month)          # 逐折 / 逐月，看波动
    out = run.log_output(df, name="features_v2", path="steps/…/outputs/features_v2.parquet", stage="features",
                          description="一行 = 一个 SKU 的一个月，加了近 6 月均值，7.1 训练用")
    run.log_model("steps/…/outputs/model.json", "sku_demand_linear")   # 见第 7 节
    run.set_conclusion("验证期 MAE 6.7959，低于最好的基线（近 6 月均值）6.9544", validity="有效")
```

- `hypothesis`：运行前写下要验证什么。`set_conclusion` 的 `validity`：**有效**（实验本身成立，结论可用，不论好坏）/ **无效**（实验本身有问题，例如用到了未来信息，结果作废，停止规则也不会把它算作最好成绩）/ **无结论**（看不出好坏）。
- `log_output` 会把输出登记为新数据版本（产出步骤 = 本步，上游 = 本次输入），并自动生成与每个输入的对比摘要。
- 用命令行包一层可以把日志、退出码、命令一起记下，脚本里的 SDK 写进同一条记录：

  ```
  uv run dsflow run 7.1 -p . -- python -m dsflow.tracking.notebook steps/07_模型选择与训练/7.1_线性模型训练/nb_7.1.ipynb
  ```

- 指标方向（越小越好 / 越大越好）写在 `dsflow.yaml` 的 `metric_goals`；没写时按名称推断（MAE、误差等越小越好，AUC、准确率等越大越好）。

## 5. 写步骤说明卡

每一轮目录下放 `step_card.yaml`（完整模板：`templates/step_card.yaml`）。首屏只回答四件事，其余放在展开区：

```yaml
step: "1.2"
headline: 清洗完成：订单行 121,000 → 119,998，可以进入 2.1 和 3.1   # 做完了吗、能否继续
can_continue: true
core_numbers:
  - label: 订单行
    before: 121000
    change: -1002
    after: 119998
    scope: 订单明细记录数（不是不同订单号个数），2024-07 至 2026-06
    source: "outputs/row_ledger.csv#sql:SELECT 行数 FROM data WHERE 处理 = '清洗后'"
operation: 删除完全重复行和未来日期；商品名称统一全角/半角；退货行、金额未知只标记不删除
exceptions: []            # 只列会影响判断的例外
artifacts:
  - {path: outputs/orders_clean.parquet, purpose: 清洗后订单明细, kind: table}
can_say: [...]            # 现在能说什么
cannot_say: [...]         # 还不能说什么
examples:                 # 真实例子：输入记录 → 规则 → 输出记录 → 所在产物
  - {title: …, input: …, rule: …, output: …, artifact: outputs/…, real: true}
```

**数字核对**：平台按 `source` 从产物重算「处理后」（`after`），与卡上的数字比较（按卡上写的小数位四舍五入）。`source` 写成 `产物路径#取值方式`，路径先按本轮目录解析，再按项目根目录：

| 取值方式 | 含义 |
|---|---|
| `rows` | 行数 |
| `sum:列` `count:列` `distinct:列` `mean:列` `min:列` `max:列` | 对某一列求合计 / 非空个数 / 不同值个数 / 均值 / 最小 / 最大 |
| `sql:查询` | 只读 SQL，表名 `data`，取第一行第一列 |
| `/a/b` | JSON 文件里的指针（`outputs/x.json#/删除完全重复行`） |

**术语检查**：说明卡与本轮报告里的**加粗短词**要在 `vocabulary.json` 登记过；`avoid` 里列的不推荐说法会被指出应统一成哪个术语。不造新概念：新术语先登记（写明出处：数据表字段、表名或既有对话）再用。

**报告过期**：报告写于最新一次成功运行开始之前，看板会提示；如果说明卡上带出处的数字按最新产物重算全部一致，会降为"提示"。

### 步骤页的三层：业务层 ｜ 数据层 ｜ 执行层

每一步、每一轮次的页面都是同样三层，别的选项卡没有了：

| 层 | 选项卡 | 内容 | 你要落盘的文件 |
|---|---|---|---|
| 业务层 | 讲解、看板 | 讲解是 notebook 导读（开头六段 + 逐格旁注）；看板是业务一页：讲解思维导图（背景 / 目的 / 结论 / 操作 / 结果 / 下一步，每个问题展开答案与业务含义）、图像与核心数字（说明卡 `artifacts` 里 `kind: figure` 的图直接显示；`core_numbers` 能画条形图就画，否则指标卡片）、分析结论 / 易错点、轮次递进、等用户处理的事。所以**每一步能出图就在说明卡里登记图，出不了图就把核心数字写全** | `guide.yaml`、`step_card.yaml` |
| 数据层 | 数据 | 存量账：**原存量**（执行前有用的表）→ **增减量**（新增 / 更新 / 退出；没有就空着）→ **后存量**（执行后有用的表），每张表整张打开；只读没改的表在原存量卡上标「本步核对」 | `dsflow data add / link / replace`、SDK `log_output` |
| 执行层 | 执行计划、代码、执行日志、产物 | 计划与审批记录；notebook 与代码；运行记录与执行记录文件；产物图（进来的表 → 这一步 → 出去的产物：登记的表、说明卡声明的文件、报告、模型）和本轮目录里的全部文件 | `plan.md`、`nb_*.ipynb`、`dsflow run`、`step_card.yaml` 的 `artifacts` |

**产物的口径**：产物统一指**最终的、有实际用处的文件**——后续阶段要用的表、给业务看的报告（用户报告、验收报告）、登记的模型、说明卡里写明用途的文件。中间产物、只为核对用的清单、验证后的一次性结果都不算，本轮目录里没登记的 csv 不会出现在数据层（只能在执行层「产物」底下的全部文件里找到）。

同一份存量账也用在阶段板块的「数据主线」和项目总览的「数据 › 数据主线」，所以登记做一次，三层都对。

平台从四个地方知道一个步骤碰了哪些表（前三个要你登记或运行，第四个自动）：

```bash
# 1. 产出的表：登记时写清上游和产出步骤，平台据此算出「输入 → 产出」和列变化
uv run dsflow data add . steps/…/outputs/wide.parquet --name 宽表 --stage features --parent 权威明细 --produced-by 1.5

# 2. 读过没改的表：用 dsflow run 跑的步骤，run.input() 已经记下了，什么都不用做
# 3. 没走过 dsflow run 的老项目（比如只读接入的），手工补挂：
uv run dsflow data link . 采购单_p1 --step 1.3 --role 核对
```

**校验型步骤没有产出也要挂上来**，否则页面上是空的，看的人会以为漏了。挂上之后平台会直说「这一步没有改动任何数据，它对这几张表做的是核对」。

**数据集名也受用词规则约束**：用数据表里有的说法（`采购单_p1`、`商品列表_整理后`），不要另造（`订单表`、`主表`）。

**打开全貌要先转 Parquet**：csv 秒转，xlsx 慢（实测 145 MB 约 335 秒），转一次按内容哈希缓存，之后秒开，原文件不动。30 MB 以下的表打开时自动转；更大的页面会显示预估时间让用户自己点，不会偷偷开始。

**讲解开头会被拿去用**：流程图节点、阶段概况、看板上显示的「目的 / 结论 / 能否继续」都取自当前轮次 `guide.yaml` 的 `brief`，没有导读的步骤才退回注册表原话并标明是原话。所以 `brief` 六段要写成脱离上下文也能看懂的话。

### 讲解：notebook 导读（guide.yaml）

步骤页默认打开的是「讲解」：**左边是这一轮 notebook 里真实的单元格与输出，右边是你写的旁注**。这是每一步最核心的内容，也是负责人真正会读的东西。

**读者是谁**：懂业务、懂技术原理、能读代码，但没做过数据科学的负责人。他看得懂 `groupby`，看不懂"QC""泄漏""holdout"；他要的是"这一格在干什么、为什么非做不可、输出里那个数字说明了什么"，不是把用户报告再抄一遍。

**怎么写**：

```bash
uv run dsflow guide init <项目目录> 1.2            # 按 notebook 真实单元格生成骨架（每格列出行数与第一行）
uv run dsflow guide check <项目目录> --step 1.2    # 核对引用与数字
uv run dsflow guide lint <项目目录> --step 1.2     # 体检用词、篇幅、有没有照搬报告
uv run dsflow guide put <项目目录> 1.2 guide.yaml  # 放到平台读得到的位置，并自动体检一次
```

```yaml
step: "1.2"
notebook: nb_1.2.ipynb          # 相对本轮目录；不写就取本轮第一个 notebook
brief:                          # 开头只有六段，每段一句，别写第二句
  background: 背景：为什么要有这一步；后续轮次写的是和上一轮的关系，不是和上一步
  question: 目的：这一步要回答什么（用业务的话，不用术语）
  answer: 结论：回答上面那个问题，最多带一个数字
  can_continue: true
  did: 操作：做了什么，一句白话，不写数字
  result: 结果：这些操作做完留下了哪些核心产出、它们现在能干什么（写产物名，和目的、操作对得上）
  next: 下一步建议：接下来该做什么、可以不做什么
parts:                          # 按 1～3 个"读者要弄明白的问题"分段
  - question: 删掉的行到底是些什么？
    answer: 一句话回答，含数字
    meaning: 业务含义：这段结论对业务意味着什么
    cells:
      - cell: 3                 # notebook 里第几个单元格（从 1 数，说明单元格也算；几格一起讲写成 [3, 4]）
        title: 按台账逐项删行
        what: 做什么：对 orders.csv 的哪几列做了什么操作、得到什么（完整的一句话，带具体宾语）
        why: 为什么：不这样做会出什么问题
        read: 输出结果讲解（至少 60 字）：指着输出里的数字说它是什么、和预期或上一步比怎么样、说明了什么
        lines:                  # 只给不容易看懂的行加注，一格最多三条，每条是完整的一句话
          - {line: 4, note: 这一行按订单号、SKU 两列判断重复，同一张订单的不同 SKU 不算重复。}
terms:                          # 只写本步特有的说法；通用词平台内置了术语表
  - {term: 行数台账, plain: 一张记录"每一步删了多少行"的表，用来核对前后行数是否一致}
cannot_say:                     # 易错点：这一步没有证明什么
  - 行数一致不代表每个字段的值都对。
```

**每一句要能单独看懂**（`docs/讲解写法.md`）：主语 + 动词 + 具体宾语（表名、列名、文件、术语、数字）+ 结果，以句号结尾；不用口语缩略动词（对上、合上、钉死、站住、跑通……），抽象词（口径、主线……）没登记就不用。「输出结果讲解」至少 60 字，要讲清输出里的数字是什么、和预期比怎么样、说明了什么。此前的数据视图（`data`）已经从讲解里去掉：整张表在数据层打开，讲解只讲代码和输出。

**平台会核对**：引用的 notebook、单元格、行号必须存在；讲解里写的每个数字都会回到所引用单元格的代码或输出里找一遍，找不到的会在页面上标出来（页头显示「数字核对 n/m」）。所以**数字照输出原样写**，不要自己换算、四舍五入。注意：平台只查行号存不存在，**查不了行注说的是不是那一行**，写完跑一遍
`uv run python scripts/show_guide_lines.py <项目目录> [步骤]`，它把每条行注和它指着的那行代码并排打出来，自己比一遍。

**每一轮都要写**，不只是当前轮次：历史轮次的导读讲的是「那一轮为什么返工、改了什么、为什么还是没过」，
背景那一段写和**上一轮**的关系（不是和上一步）。计划了却没执行的轮次也要写，只写 `brief`、不写 `parts`，
在「易错点」（`cannot_say`）里说清没有产物——这样看的人才知道是真的没做，不是漏写了。

**体检会拦住你**（`dsflow guide lint`，项目 `.claude/settings.json` 里还挂了 hook，改完导读自动跑，不通过就退回）：

| 查什么 | 不通过的样子 |
| --- | --- |
| 用词 | 项目 `vocabulary.json` 里登记了 `avoid` 的说法出现了一次。已登记的术语（含本步 `terms`）不算——「订单」要避开，列名「订单号」照用 |
| 句子 | 不以句号结尾；用了口语缩略动词（对上、合上、钉死、站住、跑通……，清单见 `docs/讲解写法.md`）；抽象词（口径、主线、门槛……）没在术语表里；「做什么」「输出结果讲解」没有点名具体对象；「做什么」「为什么」不足 18 字、「输出结果讲解」不足 60 字 |
| 开头六段 | 少一段，或者 背景 > 110 字、结果 > 90 字、目的 / 结论 / 操作 / 下一步 > 70 字 |
| 数字 | 结论里超过一个数字，或者操作里写了数字 |
| 篇幅 | 单格 `title` > 28 字、`what` > 130、`why` > 150、`read` > 420，行注超过三条 |
| 照搬 | 讲解里出现和本轮报告一字不差的长句 |

**术语提示**：正文里第一次出现的术语自动加虚线下划线，鼠标停上去看白话解释。词表优先级：本步 `terms` > 项目 `vocabulary.json` > 平台内置术语表（`dsflow/explain/glossary.yaml`，QC、主键、口径、泄漏、基线、MAE 等 50 多个）。遇到内置表里没有、项目里也没登记的行话，就地写进本步 `terms`。只读项目改不了项目目录，`vocabulary.json` 就放平台目录（`DSFLOW_HOME/projects/<id>/vocabulary.json`），平台会和项目自带的那份合起来用。

**还没有导读时**，讲解退回到「说明卡结论 + notebook 原文 + 术语提示」，并提示该跑哪条命令补。演示项目 `examples/demo_project/steps/*/*/guide.yaml` 是完整的例子；只读项目的导读放在平台目录。

### 用户报告

本轮目录下的 `report.md` / `user-report.md` 是「用户报告」标签的内容，按 data-science skill 的写法写：开头一句说做完了吗、最重要的业务结果、能否继续；正文按读者要弄明白的问题分节；至少给一个真实可核对的例子（输入记录 → 规则 → 输出记录 → 所在产物）。以加粗标签开头的段落会渲染成提示块：`**结论**：`、`**发现**：`、`**操作**：`、`**例子**：`、`**注意**：`、`**业务含义**：`、`**下一步**：`、`**补充**：`。除这些标签外，加粗只用于术语表里登记过的术语。产物用相对链接（`[行数台账](outputs/row_ledger.csv)`），点开就是该文件或数据视图。

### 执行 notebook

平台自带一个不依赖 Jupyter 内核的执行器，逐格执行并把输出写回 notebook：

```bash
uv run dsflow run 1.2 -p <项目目录> -- python -m dsflow.tracking.notebook steps/…/nb_1.2.ipynb
#   --param 名=值   注入参数（沿用 papermill 的 parameters 标签约定），用来跑不同的特征组合
#   --save-to 路径  另存，不改原 notebook（探索性的尝试用它，正式那次再原地执行）
```

notebook 里用不了 `with dsflow.start_run(...)` 跨格，所以第一格 `run = dsflow.start_run(...)`，最后一格 `run.end()`。限制：不支持 IPython 魔法命令（`%`、`!` 开头的行）。

## 6. 待决事项与决策

需要用户裁定的问题写在本轮 `outputs/decisions_required.json`，平台只读显示（每个步骤取当前轮次的那份）：

```json
{
  "schema_version": "1",
  "待决事项": [
    {"id": "D1", "问题": "月度汇总按下单时间还是支付时间？", "推荐答案": "下单时间", "依据": "支付时间缺失 12%",
     "备选差异": "支付时间口径更贴近收入", "影响范围": "1.2 全部特征", "是否阻塞后续执行": true, "状态": "unresolved"}
  ]
}
```

用户裁定后，把 `状态` 改为 `resolved` 并写上裁定结果。问题、决策日志（背景、决策、依据、放弃的方案、影响范围）也可以在平台"问题与决策"页记录，或用 HTTP API（见第 9 节）。**不替用户裁定。**

## 7. 模型与交付

1. **登记**：训练脚本里 `run.log_model(模型文件, "模型名")`，登记为**候选**，关联本次运行——训练数据版本、代码版本、指标都从运行记录追溯。同样内容的文件只算一个版本；**不要覆盖已登记的模型文件**，重新训练的结果会成为新版本。命令行：`uv run dsflow model add . <文件> --name <模型名> --run <运行编号>`。
2. **状态**：候选 → 已验收 → 已交付，可以退回上一级；每次变更要写理由，记入历史。往上走的门槛：
   - 已验收：产出运行成功、结论「有效」、记录了指标、训练数据已登记版本、模型文件与登记时一致（代码版本可还原、产出步骤已验收只提示不拦）。
   - 已交付：以上全部 + 交付清单齐全。
   - **状态由用户确认**（平台"模型与交付"页，或 `dsflow model promote … --note "理由"`），agent 不替用户变更。
3. **交付清单**：`uv run dsflow delivery init . <模型名>` 生成 `delivery/<模型名>/checklist.yaml`：
   - 平台填：`model`、`version`、`reproduce`（复现入口）、`data`（训练数据版本）、`metrics` 的数值；
   - agent 补（写着「待填」的地方）：`summary` 一句话说明、`usage` 使用入口、`applicability`（适用范围、不适用的情况、训练数据期间、已知弱点）、`monitoring`（看什么、阈值、频率、超过后做什么）、每个指标的 `scope` 口径与 `baseline` 对照、`deployment`（未定写「待定」）、`open_items` 遗留问题；
   - 再次运行 `delivery init` 只刷新平台填的部分，人写的保留；
   - `uv run dsflow delivery check . <模型名>` 全部通过（退出码 0）才算齐全。模板与示例：`templates/delivery_checklist.yaml`。

## 8. 交接前自查

```
uv run dsflow validate .   # 注册表规则
uv run dsflow check .      # 告警 + 说明卡数字核对 + 术语检查
uv run dsflow next .       # 现在在哪一步、本轮目录缺什么文件、下一步做什么（--json 给 agent 读）
```

`dsflow check` 在有**严重 / 重要**告警或数字不一致时退出码为 1。告警含义：

| 等级 | 告警 |
|---|---|
| 严重 | 原始数据被改或不见了 |
| 重要 | 注册表校验未通过；标为已完成但当前轮次不是已完成、或说明卡写着暂不能继续；已验收 / 已交付的模型文件被覆盖或不见了 |
| 注意 | 最近一次运行失败；报告早于最新运行；标为已完成却没有主验收报告；已交付的模型交付清单不齐全 |
| 提示 | 报告早于最新运行，但说明卡上的数字按最新产物重算全部一致 |

## 9. MCP 服务与插件

支持 MCP 的 agent 可以不走命令行：`uv run dsflow attach <目录> --mcp` 在项目里写 `.mcp.json`，agent 启动时会拉起 `python -m dsflow mcp`（stdio，需要 `uv sync --extra mcp`），拿到这些工具：

| 工具 | 做什么 |
|---|---|
| `next` | 在哪一步、处于哪个环节、缺什么文件、该做什么（同 `dsflow next --json`） |
| `list_steps` / `read_file` | 步骤清单；读项目里的文本文件 |
| `read_guide` / `lint_guide` / `put_guide` | 读讲解（含核对结果）；体检；写入并立刻核对、体检 |
| `approvals` / `decide` | 审批记录；记录用户在对话里的审批（来源标为「MCP」） |
| `validate` / `check` | 注册表校验；交接前核对 |

等平台上的审批不走 MCP（调用不该长时间阻塞），仍由宿主运行 `dsflow await`。

Claude Code 还可以整体挂插件：`claude --plugin-dir <DSFlow 仓库>/plugin`，插件带 `dsflow-project` skill、讲解体检 hook 和 `dsflow mcp`，在任何目录都可用；项目级的 AGENTS.md、CLAUDE.md、可写登记仍由 `dsflow attach` 完成。

## 10. HTTP API 速查

平台默认在 `http://127.0.0.1:8790`（`uv run dsflow ui`）。`{id}` 是项目编号（`dsflow projects` 查看）。

| 方法与路径 | 用途 |
|---|---|
| `GET /api/projects/{id}` | 流程图、校验问题 |
| `GET /api/projects/{id}/steps/{步骤}` | 步骤详情（轮次、文件、说明卡） |
| `GET /api/projects/{id}/steps/{步骤}/checks` | 数字核对与术语检查 |
| `GET /api/projects/{id}/board` | 看板（告警、需要关注、迭代、动态） |
| `GET /api/projects/{id}/runs`、`/runs/{运行}` | 运行记录与复现卡片 |
| `GET/POST/PATCH/DELETE /api/projects/{id}/tracker/{issues\|decisions\|pending}[/{编号}]` | 问题、决策、待决事项 |
| `GET /api/projects/{id}/steps/{步骤}/approval` | 审批记录条目、现在等的是审批还是确认、是否只读 |
| `POST /api/projects/{id}/steps/{步骤}/approval` | `{kind: approval\|acceptance, decision: approve\|reject, note}`：写审批记录并改状态（可写项目；403 / 404 / 409） |
| `GET /api/projects/{id}/knowledge` | 能说 / 不能说、停止规则、探索记录（界面上「知识边界」页已删，停止规则由运行页取用） |
| `GET /api/projects/{id}/models`、`/models/{名}/{版本}` | 模型登记、门槛、交付清单核对 |
| `POST /api/projects/{id}/models/{名}/{版本}/checklist` | 生成或刷新交付清单（可写项目） |

## 11. 不要做的事

- 不修改 `data/raw/`；不覆盖已登记的模型文件；不删除运行记录。
- 不替用户审批计划、裁定待决事项、把步骤改为 `done`、把模型标为已验收 / 已交付。
- 不按编号推导依赖；不在历史轮次上直接改（开新轮次）。
- 不造新概念；同一个东西始终用同一个说法。
