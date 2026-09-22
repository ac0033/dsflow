# 项目目录约定（DSFlow）

- `AGENTS.md`：跨 agent 的工作规则（计划 → 用户审批 → 执行 → 主 agent 验收 → 用户确认）；`CLAUDE.md` 只有一行 `@AGENTS.md`，Claude Code 读它。
- `.claude/`：`skills/dsflow-project/SKILL.md`（Claude Code 自动发现的 skill）和 `settings.json`（改 guide.yaml 时自动体检的 hook），由 `dsflow attach` 装。
- `dsflow.yaml`：项目名称、业务问题、原始数据集登记、指标方向（`metric_goals`）。
- `lifecycle/steps.json`：步骤注册表，是步骤、状态、依赖、轮次的唯一事实来源。依赖必须显式登记，不按编号推导。
- `data/raw/`：原始数据，只读。
- `steps/NN_阶段/X.Y_目的/`：一个步骤 = 一个稳定的业务目的。
  - `plan.md`（计划，写给用户评估）、`approval_record.md`（审批原话，由平台或 `dsflow approve` 写）
  - `src/`、`nb_X.Y.ipynb`：代码与真实执行的 notebook；用脚本执行时在注册表登记 `execution_scripts`
  - `outputs/`：产物
  - `guide.yaml`：讲解（notebook 导读，步骤页默认打开的就是它）
  - `step_card.yaml`：说明卡（一句话结论、能否继续、核心数字、产物）
  - `report.md`：用户报告（首个标题含步骤编号）；`acceptance.md`：主 agent 的验收报告
  - `revisions/rNN_日期_说明/`：返工开新轮次，历史不覆盖
- `delivery/<模型名>/checklist.yaml`：交付清单（`dsflow delivery init` 生成草稿）。
- `vocabulary.json`：术语表。报告与说明卡只用这里登记过的术语。
- `.dsflow/`：平台写入的运行记录、模型登记、问题与决策；`.dsflow/cache/` 可随时重建。

在哪一步、缺什么：`dsflow next .`；校验：`dsflow validate .`；交接前核对：`dsflow check .`
