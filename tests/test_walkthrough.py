"""协议验收：一个只拿到 HTTP 地址、不碰文件系统的模拟 agent，从空项目走完 计划 → 审批 → 执行 → 验收 → 确认。

它只调 POST /api/tools/<工具>（agent 侧）和 POST …/approval（用户点按钮）。原始数据由"用户"放进 data/raw。
"""

import json

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dsflow.cli import app as cli
from dsflow.demo import make_demo
from dsflow.index.db import PlatformIndex
from dsflow.server.app import create_app

runner = CliRunner()

NOTEBOOK = {
    "nbformat": 4, "nbformat_minor": 5, "metadata": {},
    "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": "# 1.1 确认采购单\n\n读入采购单，数行数、查空值。"},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source":
            "import csv, json, pathlib\n"
            "rows = list(csv.DictReader(open('../../../data/raw/orders.csv', encoding='utf-8')))\n"
            "empty = sum(1 for r in rows for v in r.values() if v == '')\n"
            "pathlib.Path('outputs').mkdir(exist_ok=True)\n"
            "json.dump({'rows': len(rows), 'empty': empty}, open('outputs/summary.json', 'w', encoding='utf-8'))\n"
            "print(f'行数 {len(rows)}，空值 {empty}')\n"},
    ],
}
GUIDE = """step: "1.1"
brief:
  background: 演示项目从一份三行的采购单开始，做分析之前先确认这份表能不能直接用。
  question: 这份采购单能不能直接拿来分析？
  answer: 采购单可以直接使用，共有 3 行并且没有空值。
  can_continue: true
  did: 读入采购单，统计行数并检查空值，把结果写进汇总文件。
  result: 采购单的行数与空值统计写进了 summary.csv，下一步清洗可以直接读它。
  next: 进入下一步清洗采购单，或者直接开始探索分析。
parts:
  - question: 采购单有多少行、有没有空值？
    answer: 采购单有 3 行，空值有 0 个。
    meaning: 行数和空值决定后面按订单号统计的数量能不能直接算。
    cells:
      - cell: 2
        title: 统计行数与空值
        what: 读入 orders.csv 的全部行，统计行数与空值个数，写进 outputs/summary.json。
        why: 行数或空值不对，后面按商品名称统计的数量就会算错。
        read: 输出里的行数 3 是采购单的记录数，空值 0 表示每一列都填满了，和计划里预期的三行样例一致，说明这份采购单可以直接用于后面的统计。
"""
STEP_CARD = """step: "1.1"
headline: 采购单可以直接使用，可以进入下一步。
can_continue: true
core_numbers:
  - label: 采购单行数
    after: 3
    unit: 行
    scope: orders.csv 的记录数（不是不同订单号个数）
    source: "outputs/summary.json#/rows"
artifacts:
  - path: outputs/summary.json
    purpose: 行数与空值的汇总，供后面核对
    kind: table
"""
REPORT = "# 1.1 确认采购单\n\n**结论**：采购单可以直接使用，共 3 行，没有空值。\n\n**操作**：读入 orders.csv，统计行数与空值，结果在 [汇总](outputs/summary.json)。\n"
ACCEPTANCE = "# 1.1 验收\n\n**结论**：执行通过。从 data/raw/orders.csv 独立数出 3 行、0 个空值，与 outputs/summary.json 一致。\n"


def test_remote_agent_completes_a_round_over_http(tmp_path):
    root = tmp_path / "demo"
    info = make_demo(root)  # 用户：建项目（带原始数据与一份等审批的计划）
    pid = info["id"]
    client = TestClient(create_app(PlatformIndex(), mcp=False))

    def tool(_name, **args):
        env = client.post(f"/api/tools/{_name}", json={"project": pid, **args}).json()
        assert env["ok"], (_name, env)
        return env["data"]

    # 计划已经在等审批（demo 建好的状态）；agent 先看 next
    nxt = tool("next")
    assert nxt["phase"] == "await_approval" and nxt["tool_calls"][0]["tool"] == "approval_wait"
    assert tool("approval_wait", step="1.1", timeout=1)["result"] == "pending"
    # 用户：网页上点「通过」
    r = client.post(f"/api/projects/{pid}/steps/1.1/approval", json={"kind": "approval", "decision": "approve", "note": "可以。"})
    assert r.status_code == 200 and r.json()["to"] == "in_progress"

    # agent：执行，只用工具
    nxt = tool("next")
    assert nxt["phase"] == "execute"
    d = nxt["step"]["dir"]
    tool("file_write", path=f"{d}/nb_1.1.ipynb", content=json.dumps(NOTEBOOK, ensure_ascii=False))
    run = tool("run_exec", step="1.1", target=f"{d}/nb_1.1.ipynb", hypothesis="采购单没有空值", timeout=120)
    assert run["status"] == "succeeded", run
    assert "行数 3" in run["log_tail"]
    tool("data_register", path="data/raw/orders.csv", name="采购单", stage="raw", description="一行 = 一个采购行")
    tool("file_write", path=f"{d}/report.md", content=REPORT)
    tool("file_write", path=f"{d}/step_card.yaml", content=STEP_CARD)
    init = tool("guide_init", step="1.1")
    assert init["existed"] is False and "cell" in init["text"]
    put = tool("guide_put", step="1.1", text=GUIDE)
    assert put["lint"] == [] and put["checks"]["missing"] == [], put
    assert tool("validate")["ok"] is True
    chk = tool("check", step="1.1")
    assert chk["ok"] is True, chk["alerts"]
    assert tool("step_set_status", step="1.1", status="awaiting_acceptance")["to"] == "awaiting_acceptance"

    # 主 agent：验收
    nxt = tool("next")
    assert nxt["phase"] == "acceptance"
    assert tool("guide_check", step="1.1")["missing"] == []
    assert tool("guide_lint", step="1.1") == []
    tool("file_write", path=f"{d}/acceptance.md", content=ACCEPTANCE)
    assert tool("next")["phase"] == "await_confirmation"

    # 用户：确认完成
    r = client.post(f"/api/projects/{pid}/steps/1.1/approval", json={"kind": "acceptance", "decision": "approve", "note": "看懂了。"})
    assert r.status_code == 200 and r.json()["to"] == "done"
    nxt = tool("next")
    assert nxt["phase"] == "all_done" and nxt["tool_calls"][0]["tool"] == "step_add"

    # agent：登记下一步
    added = tool("step_add", step="1.2", stage=1, title="清洗采购单", depends_on=["1.1"], op="去掉重复行")
    assert added["dir"].endswith("/1.2_清洗采购单")
    assert tool("next")["phase"] == "plan"
    # 网页看到的一切都来自项目文件
    detail = client.get(f"/api/projects/{pid}/steps/1.1").json()
    kinds = {f["rel"]: f["kind"] for f in detail["revisions"][0]["files"] if "/" not in f["rel"]}
    assert kinds["acceptance.md"] == "acceptance_report" and kinds["approval_record.md"] == "approval" and kinds["guide.yaml"] == "guide"
    assert client.get(f"/api/projects/{pid}/steps/1.1/approval").json()["entries"][-1]["note"] == "看懂了。"


def test_step_add_guards(mini_project):
    root, _ = mini_project
    client = TestClient(create_app(PlatformIndex(), mcp=False))
    call = lambda name, **a: client.post(f"/api/tools/{name}", json={"project": str(root), **a}).json()  # noqa: E731
    assert call("step_add", step="1.1", stage=1, title="重复")["error"]["code"] == "conflict"
    assert call("step_add", step="3.1", stage=9, title="没有的阶段")["error"]["code"] == "invalid"
    assert call("step_add", step="3.1", stage=2, title="依赖不存在", depends_on=["8.8"])["error"]["code"] == "invalid"
    out = call("step_add", step="2.2", stage=2, title="第二步", depends_on=["2.1"])
    assert out["ok"] and out["data"]["order"] == 4 and (root / out["data"]["dir"]).is_dir()


def test_demo_command(tmp_path):
    target = tmp_path / "demo"
    result = runner.invoke(cli, ["demo", str(target)])
    assert result.exit_code == 0, result.output
    assert "接下来三步" in result.output and "dsflow await" in result.output
    assert (target / "data/raw/orders.csv").is_file() and (target / "AGENTS.md").is_file()
    nxt = json.loads(runner.invoke(cli, ["next", str(target), "--json"]).output)
    assert nxt["phase"] == "await_approval"
    assert runner.invoke(cli, ["demo", str(target)]).exit_code == 1  # 目录非空就拒绝
