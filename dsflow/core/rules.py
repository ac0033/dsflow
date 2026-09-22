"""工作规矩：接入 DSFlow 的 agent 每个项目都要守的几条，在这里定义一次。

协议文档（`dsflow protocol`、`GET /api/protocol`、工具 `protocol_get`）、`next` 的返回、MCP 服务的
instructions、终端客户端的系统提示都从这份清单读；写进文档、skill、AGENTS.md 的同名段落由
tests/test_rules.py 逐个文件核对，哪个接口漏了都会红。
"""

from __future__ import annotations

WORK_RULES: list[dict[str, str]] = [
    {
        "id": "preflight",
        "title": "开工前先检查环境",
        "rule": "接入平台之后、写第一份计划之前，先调 env_check 确认分析环境建好了：项目有自己的 .venv，平台的 dsflow 挂进了这个环境，"
                "pandas 这些后面要用的库能真的 import 进来。",
        "why": "环境缺一半时，agent 要到执行 notebook 那一刻才发现报错，那时计划已经批过、时间已经花掉，只能退回重做。",
        "how": "env_check 返回 ready 为 false 就先调 env_prepare（命令行：dsflow attach <项目目录> --venv）把环境补齐，再写计划；"
               "计划里要用基础分析库以外的库，在 env_check 的 imports 里一起确认。",
    },
    {
        "id": "step_boundary",
        "title": "一步是一个完整独立的单元",
        "rule": "登记步骤和写计划时，一步围绕一个完整的业务目的：它有自己的输入、自己的产物、自己能核对的验收标准，做完能单独讲给用户听。",
        "why": "把一个阶段的操作全堆在一步里，用户在中间没法评估，出问题要整步重做；把一个操作拆成三步（读文件一步、改列名一步、存盘一步），"
               "每一步都没有能交付的产物，审批和验收就空转。",
        "how": "两个问题都答「能」才算一步：这一步的产物能不能被下一步直接使用？验收标准能不能只看本步产物核对？"
               "答「不能」就合并或者拆开，拆开之后每一步各自用 step_add 登记、各自写计划。",
    },
]

RULE_TITLES = tuple(r["title"] for r in WORK_RULES)


def brief() -> list[dict[str, str]]:
    """给 next 返回的短版：每条只带编号、标题、一句话规矩。"""
    return [{"id": r["id"], "title": r["title"], "rule": r["rule"]} for r in WORK_RULES]


def one_line() -> str:
    """给系统提示、MCP instructions 这类只能放一段话的地方。"""
    return "；".join(f"{r['title']}（{r['rule']}）" for r in WORK_RULES)


def rules_markdown() -> str:
    """协议文档里的「工作规矩」一节，由这份清单生成。"""
    lines = ["<!-- 由 `dsflow protocol --format markdown` 生成（工作规矩）；不要手改 -->", ""]
    for i, r in enumerate(WORK_RULES, 1):
        lines += [f"### {i}. {r['title']}", "", r["rule"], "", f"- **为什么**：{r['why']}", f"- **怎么做**：{r['how']}", ""]
    return "\n".join(lines)
