# DSFlow · 数据科学项目全周期追踪平台

[![CI](https://github.com/ac0033/dsflow/actions/workflows/ci.yml/badge.svg)](https://github.com/ac0033/dsflow/actions/workflows/ci.yml) [![Release](https://img.shields.io/github/v/release/ac0033/dsflow?include_prereleases&label=release)](https://github.com/ac0033/dsflow/releases) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) ![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)

本地单机版平台：把数据科学项目的每一步变成**可检查的状态变化**——做了什么、数据怎样变化、凭什么说做对了、现在能说什么和不能说什么。类似 MLflow（运行追踪）+ DVC（数据版本），重点补 L3（状态变化）与 L4（认知追踪）。

- 项目文件是唯一事实来源（`lifecycle/steps.json`、步骤说明卡、运行记录），平台只读取、校验、展示；SQLite 只是可重建的索引。
- 已有项目默认**只读接入**：平台不在项目目录写任何文件。
- **项目状态：公开预览**。代码与功能已公开，可在本机安装试用；多用户登录与服务器部署尚未完成，暂不提供在线服务。版本变化见 [docs/CHANGELOG.md](docs/CHANGELOG.md)，第一次安装看 [docs/接入指南.md](docs/接入指南.md)。

## 界面：三个层级 × 三个层面

按生命周期分三个层级——**项目总览 → 阶段 → 步骤**，左侧菜单就是它们。每个层级都按同样三个层面组织：

| 层面 | 回答什么 | 项目总览 | 阶段 | 步骤（每一轮次都一样） |
|---|---|---|---|---|
| **业务层** | 做了什么、结论是什么 | 看板、流程图、问题与决策 | 概况（每步一句目的、一句结论、能否继续） | **讲解**（notebook 导读）、**看板**（讲解思维导图、图像与核心数字、分析结论 / 易错点、轮次递进、等你处理的事） |
| **数据层** | 产物从什么变成了什么 | 数据 › 数据主线（按阶段按步骤的存量账）、数据文件（只列不属于某一阶段的）、版本对比、演变链 | 数据主线（本阶段）、数据文件（本阶段的，含中间文件） | **数据**（原存量 → 增减量 → 后存量 → 中间产物：增减量只讲变化，每张表整张打开在前后存量里） |
| **执行层** | 怎么做的 | 运行与实验、模型与交付 | 运行记录 / 实验对比、模型 | **执行计划**、**代码**、**执行日志**、**产物**（产物图 + 本轮全部文件） |

**看不懂就问**：答疑的模型能自己去读项目——`file_read` 读代码、notebook、计划与报告的原文，`data_peek` 看一张表的前几行与全部列名，`data_query` 对这张表跑一条只读 SQL 数一数、分组汇总（只能 SELECT，改不了任何东西）。答完以后，答案里提到的数据文件与单元格会列成可以点的去处：数据文件跳到那一步的「数据」并整张打开，单元格跳到「讲解」里的那一格。

任何页面上选中一句话，浮出来的是两个按钮。「问 AI」把这句话连同它周围的原文、当前步骤的讲解开头、已登记的术语一起交给模型，马上问；「标注」就地写一句自己的备注，点「确认标注」后先留在页面上不发送——可以接着标别处，几处标完在对话框里写一个问题一起发过去，答完这几句都钉在页面上，下次进来仍然高亮，点一下就回到那条问答。模型只有读项目的工具（读文件、看数据表前几行、看讲解与运行记录），改不了项目里的任何东西；答完平台会把答案里的数字回到原文里核对一遍，找不到出处的会列出来提醒。第一次用先在对话框顶部配模型：选一家（Claude / DeepSeek / 通义千问 / Kimi / 智谱 / OpenRouter / 本机 Ollama）、粘上密钥、点「保存并连接」，平台会真的发一句话过去测通；密钥只写进本机的 `models.json`（这几个接口只接受本机请求），和 `dsflow chat` 共用一份配置。问答与标注存在平台目录，只读项目也不写项目目录；答疑里解释清楚的行话可以一键收进项目术语表，收完不用刷新，这个词在页面上当场就带下划线、能悬停看解释。

**行话哪里都能查**：讲解、执行计划、代码说明、报告里出现的术语，第一次出现时加虚线下划线，鼠标停上去看白话解释，点一下把解释钉住（钉住后能选中里面的字，按 Esc 或点别处收起）；解释框永远摆在窗口里面，不用横向拖页面去看后半句。文末列出本篇出现过的术语。术语来自三层——本步讲解登记的 > 项目术语表 > 平台内置。术语表里还没有的词，选中直接问 AI。

**数据怎么变的**：步骤页的「数据」分四段——原存量（执行前有哪些有用的表）、增减量、后存量（执行完剩哪些）、中间产物（本轮留下、没进存量账的数据文件，默认折起来，展开能整张打开；报告与说明卡这类不是数据表，在「产物」里看）。增减量**只讲变化**：哪几张表做成 / 合并成了哪张表，行从多少变成多少，列从多少变成多少，新增与消失的列名各列一遍；整张表的内容在前后存量里打开，不在增减量里重复一遍。

**一列为什么变**：增减量里每个列名都能点开——它是新增、消失还是取值有变化，讲解里哪一段说过它（带原话），notebook 哪一格的代码动了它，一键跳到讲解的那一格。「取值有变化」要把两张表各做一遍画像才知道，所以点一下再算；算完这几列在「打开全貌」里标蓝（新增的列标黄），一眼看出这一步动了哪些列。

**数据文件在哪找**：每个数据文件按两条线归到阶段——放在这个阶段的步骤目录下，或者登记数据集时写明由这一步产出。阶段页的「数据文件」按步骤分组列出本阶段的全部文件（含中间文件），项目总览的「数据文件」只列不属于任何阶段的文件（原始数据、全项目共用的表）。两处的清单都能搜索、能按目录折叠、能只看已登记的数据集。

**产物的口径**：只算有用的最终文件——后续要用的表、给业务看的报告、模型；中间结果、核对清单、一次性验证结果不算。新表替代旧表时声明 `replaces`，旧表退出「后存量」。三个层级的数据层同一份来源（每步的存量账）；讲解和数据互相能跳。讲解、说明卡、数据登记都由执行 agent 落盘，平台只渲染、核对、体检。

## 接入 agent：六个入口

想用三分钟看完整条链路：先按 [安装](#安装) 装好 `dsflow`，再运行 `dsflow demo`。它会建立一个已写好计划、正在等待审批的演示项目，并在屏幕上打印三步——① 启动平台并打开它给出的步骤网址，查看 agent 提交的计划与页头的审批条；② 另开一个终端运行它给出的 `dsflow await <演示项目目录> 1.1`，这条命令扮演正在等待审批的 agent；③ 回到网页填写一句审批意见并点击「通过」，第 ② 步的命令随即退出并打印这句意见。整个过程不需要任何大模型。

| 入口 | 目标用户 | 用法 |
|---|---|---|
| **协议文档** | 任何 agent 与开发者 | [docs/agent-protocol.md](docs/agent-protocol.md)；机器可读 `dsflow protocol --format json` / `GET /api/protocol` |
| **MCP** | 支持 MCP 的 agent | 本机：`dsflow attach <目录> --mcp` 写好 `.mcp.json`（stdio）；远程：`http://<平台>:8790/mcp`（streamable HTTP，带令牌） |
| **命令行** | 能执行 shell 命令的 agent | `dsflow call <工具> --args '<json>' -p <目录>`，或 `dsflow next / await / approve …` |
| **终端客户端** | 不另行安装 agent 的用户 | `dsflow chat`：`/models add 我的模型 --preset deepseek --api-key sk-…`，`/project <目录>`，然后直接对话；模型通过同一套工具推进项目 |
| **Skill** | 不接入平台、只采用这套方法与文件结构的用户 | [skills/data-science-project](skills/data-science-project)（能力）+ [skills/dsflow-project](skills/dsflow-project)（接口） |
| **Claude Code 插件** | 用 Claude Code 的用户 | `claude --plugin-dir <仓库目录>/plugin`，skill、讲解体检 hook、MCP 服务一次装齐；见 [plugin/README.md](plugin/README.md) |

**两个角色，默认是同一个 agent**：主 agent 写计划与验收，执行 agent 执行并起草用户报告；用户不另行安排时，同一个 agent 依次担任这两个角色（自己写计划 → 用户批准 → 自己执行 → 自己验收），明确安排了独立的执行 agent 时才分开。兼任时验收仍要从落盘的产物重新核对，不复用执行时的中间结果。

**两条工作规矩，所有入口一致**：**开工前先检查环境**——接入之后、写第一份计划之前先调 `env_check`，确认项目的 `.venv`、平台的 dsflow、后面要用的库都到位，缺了就用 `env_prepare` 补齐，免得执行到一半才报错；**一步是一个完整独立的单元**——一步围绕一个完整的业务目的，有自己的输入、产物和能核对的验收标准，不把一个阶段的操作堆成一步，也不把一个操作拆成三步。两条规矩在 `dsflow/core/rules.py` 里写一次，协议文档、`next` 的返回、MCP、命令行、终端客户端、两个 skill 和项目里的 `AGENTS.md` 都从它来。

接入后发给 agent 的第一句话：「这个项目用 DSFlow 追踪，先读 AGENTS.md，动手之前调 `next`，按它的 tool_calls 做。」之后只与 agent 对话，在网页上查看进度、执行审批（每一步的流程见 [接入指南 · 之后每一步怎么走](docs/接入指南.md#之后每一步怎么走)）。

## 安装

第一次安装请按 **[接入指南（五步）](docs/接入指南.md)** 做，那里写明了每条命令在哪运行、运行完应该看到什么、报错分别是什么意思。下面是给有经验的读者看的简版。

**先选一种装法**，四种的前置条件和命令前缀各不相同，完整对照表见 [接入指南 1.1 先选一种装法](docs/接入指南.md#11-先选一种装法)：

| 装法 | 前置条件 | 命令 | 平台目录 |
|---|---|---|---|
| **① uv 装成命令**（推荐） | uv、Git、Node.js | 任何目录 `dsflow …` | `~/.dsflow` |
| ② 不用 uv：venv + pip | 自备 Python 3.13+、Git、Node.js | 每个新终端先激活虚拟环境再运行 `dsflow …`，或写成 `python -m dsflow …` | `~/.dsflow` |
| ③ 使用他人构建的 `.whl` | 仅需 uv（或 Python 3.13+），**不需要 Git 与 Node.js** | 任何目录 `dsflow …` | `~/.dsflow` |
| ④ 在源码仓库内开发 | uv、Git、Node.js | 必须在仓库目录内运行 `uv run dsflow …` | `<仓库>/.dsflow_home` |

装法 ② ③ ④ 的命令见 [接入指南 1.3 安装](docs/接入指南.md#13-安装)；装不上时对照 [接入指南 1.5 安装报错对照表](docs/接入指南.md#15-安装报错对照表)。`.whl` 在 [Releases 页](https://github.com/ac0033/dsflow/releases) 下载，或自己运行 `uv build --wheel` 生成，按装法 ③ 安装。

### 装法 ①（推荐）

**前置条件**（逐项的安装办法见 [接入指南 1.2 前置条件](docs/接入指南.md#12-前置条件)）：uv（`uv --version`，验证过 0.11.14）、Git（`git --version`）、Node.js 20 或更新（`node --version`，验证过 v24.15.0；`npm` 随它自带，只用来构建一次网页）。DSFlow 还没有发布到 PyPI，PyPI 上的 `dsflow` 是别人的包，不要 `pip install dsflow`。

```bash
git clone https://github.com/ac0033/dsflow.git dsflow-src && cd dsflow-src
npm --prefix web install && npm --prefix web run build   # 构建网页（一次，约两分钟；用 pnpm 也行）
uv tool install ".[mcp,chat]"                            # 装成命令 dsflow，任何目录都能用
uv tool update-shell                                     # 第一次用 uv 装工具：加进 PATH，然后关掉终端重新打开
```

重新打开终端后：

```bash
cd ..                                                # 离开源码目录
dsflow doctor                                        # 逐项检查，✓ 正常、! 提示、✗ 要修（每条带修法）
dsflow ui                                            # 打开 http://127.0.0.1:8790；后面的命令在另一个终端运行
```

远程 agent 接入：`dsflow ui --host 0.0.0.0 --token <随机字符串>`，把 `http://<你的地址>:8790/mcp` 和令牌给它（请求头 `Authorization: Bearer <令牌>`）；本机浏览器不需要令牌。

## 常用命令

装成命令后在任何目录直接运行；装法 ④ 要在仓库目录内把 `dsflow` 换成 `uv run dsflow`。

```bash
dsflow --version                    # 版本号；装得全不全用 dsflow doctor 看
dsflow init <目录> --name 项目名     # 用模板新建项目（11 阶段）、接入、并准备分析环境（--no-venv 跳过）
dsflow demo [目录]                        # 三分钟演示：建一个带计划、等审批的项目，照屏幕上的三步做
dsflow attach <目录> [--mcp] [--venv]  # 已有项目接入：装 AGENTS.md、CLAUDE.md、skill、讲解体检 hook，登记为可写；--mcp 再写 .mcp.json；--venv 补分析环境
dsflow mcp                          # MCP 服务（stdio），由 .mcp.json 或插件拉起；需要 uv sync --extra mcp
dsflow validate <目录>              # 校验注册表
dsflow next <目录> [--json]         # 给 agent：现在在哪一步、缺什么文件、下一步做什么
dsflow protocol [--format json]     # 协议：工具清单（json 给机器读）；dsflow call <工具> --args '<json>' -p <目录> 调用
dsflow approve <目录> <步骤> --note "原话"   # 记录用户的审批（reject 退回、confirm 确认完成），平台改状态
dsflow await <目录> <步骤>            # agent 等用户在平台审批 / 确认；命令退出即可继续
dsflow import <目录> [--writable]   # 登记到平台，默认只读
dsflow projects                     # 列出已登记项目
dsflow schema                       # 导出数据契约 JSON Schema 到 docs/contracts/
dsflow data sync <目录>             # 登记 dsflow.yaml 里声明的数据集
dsflow data add <目录> <文件> --name 名称 --stage raw   # 登记一个数据集版本
dsflow data list <目录>             # 数据演变链
dsflow data profile <目录> <文件>   # 数据画像摘要
dsflow data compare <目录> <A> <B> --key 主键 --segment 分组列   # 两版对比
uv run pytest（仓库内）                             # 运行测试（-m "not slow" 跳过整目录哈希比对）
```

## 记录运行（SDK）

```python
import dsflow

with dsflow.start_run("1.2", hypothesis="删除完全重复行后按月需求量不失真") as run:
    run.log_input("data/raw/orders.csv", name="orders_raw")
    run.log_params({"去重方式": "所有字段完全相同"})
    run.log_output(df, name="orders_clean", path="steps/01_数据预处理/1.2_订单清洗/outputs/orders_clean.parquet")
    run.log_metrics({"删除重复行": 1000})
    run.log_metrics({"MAE": 0.52}, fold=1)          # 逐折指标
    run.set_conclusion("删除完全重复行 1,000 行", validity="有效")   # 有效 / 无效 / 无结论
```

用命令行包一层，日志、退出码、用时自动记录，脚本里的 SDK 写进同一条记录：

```bash
dsflow run 1.2 -p <项目目录> -- .venv/Scripts/python -m dsflow.tracking.notebook steps/…/nb_1.2.ipynb   # macOS / Linux 写 .venv/bin/python
dsflow runs <项目目录>              # 最近的运行
```

这里用项目自己的 `.venv`（`dsflow init` 建好的那个），因为分析库和 dsflow 都装在它里面；直接写 `python` 则取决于当前终端里的 `python` 指向哪个解释器，装法 ① 的用户可能没有这个命令。agent 走协议里的 `run_exec` 时自动用这个解释器，不用自己指定。

## 目录

```
dsflow/        后端：core（契约、校验、流程图投影、哈希）· index（SQLite 索引）· server（FastAPI）· ask（网页答疑）· chat（终端客户端）· env.py（项目分析环境）· cli.py
web/           前端：React + Vite + TypeScript + Tailwind
templates/     新项目模板、步骤说明卡模板
examples/      演示项目
docs/          接入指南、agent 协议与讲解写法、CHANGELOG、数据契约（JSON Schema）
plugin/        Claude Code 插件
tests/
```

## 安全说明

- 答疑与终端客户端的模型密钥明文保存在本机平台目录的 `models.json` 里，管理密钥的接口只接受本机请求；不要把平台目录提交进版本库或共享出去。
- `dsflow ui` 默认只监听 `127.0.0.1`。用 `--host 0.0.0.0` 对外开放时必须带 `--token`，远程请求要带 `Authorization: Bearer <令牌>`；平台没有用户登录，不要把它直接暴露在公网。
- `run_exec` 只执行项目目录内的文件，并在项目自己的 `.venv` 里运行。

## 许可

[MIT](LICENSE)。
