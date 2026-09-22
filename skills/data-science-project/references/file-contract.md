# 文件契约（与 DSFlow 平台一致）

一个步骤 = 一个稳定的业务目的，目录 `steps/NN_阶段/X.Y_目的/`；返工开新轮次 `revisions/rNN_日期_说明/`，历史不覆盖。每步、每轮只留这七个文件（加代码与产物），多出来的文件没有人读。

| 文件 | 谁写 | 什么时候 | 内容 |
|---|---|---|---|
| `plan.md` | 主 agent | 计划 | 为什么做、输入、处理办法、产物、验收标准、停止条件；写给用户评估 |
| `approval_record.md` | 平台或 `dsflow approve` | 审批与确认 | 用户原话、状态变化、依据；不要手写 |
| `nb_<步骤>.ipynb` | 执行 agent | 执行 | 真实执行的 notebook；公共代码放 `src/`；产物放 `outputs/` |
| `report.md` | 执行 agent 起草，主 agent 审阅 | 执行 | 用户报告（写法见 [user-report.md](user-report.md)），首个标题含步骤编号 |
| `step_card.yaml` | 执行 agent | 执行 | 说明卡：`headline` 一句话结论、`can_continue`、`core_numbers`（每个带 `source`，可从产物重算）、`artifacts`（能出图就登记 `kind: figure`） |
| `guide.yaml` | 执行 agent 起草，主 agent 核对 | 执行 | 讲解：只讲 notebook 单元格（做什么 / 为什么 / 输出结果讲解），开头六段 背景 / 目的 / 结论 / 操作 / 结果 / 下一步各一句，结论最多一个数字，结果写核心产出；不复述用户报告 |
| `acceptance.md` | 主 agent | 验收 | 从实际产物独立核对后写明为什么通过或未通过（写法见 [acceptance-report.md](acceptance-report.md)） |

步骤注册表 `lifecycle/steps.json` 记每步的编号、标题、目录、状态与依赖（依赖显式登记，不按编号推导）。状态机：

```
pending → pending_approval → in_progress → awaiting_acceptance → done
            （agent）        （用户通过）     （agent）        （用户确认）
```

agent 只能把状态改成 `pending_approval`（提交审批）和 `awaiting_acceptance`（提交验收）；`in_progress`、`done` 由用户的审批产生，退回时状态倒回去。没有审批不执行，没有确认不进下一步。

原始数据 `data/raw/` 只读；产出的表要登记（名字用数据表里的说法，替代旧表时声明）；术语只用 `vocabulary.json` 登记过的说法，新术语先登记出处再用；每句话要有主语、动词、具体宾语，以句号结尾。

没有平台时：按上面的结构写文件即可，`dsflow next .` 告诉你在哪一步、缺什么，`dsflow check .` 核对说明卡数字与术语，`dsflow guide lint .` 体检讲解；有平台时这些文件在网页上逐步可见、可审批。
