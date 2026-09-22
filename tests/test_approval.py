"""审批闭环：状态转换与护栏、审批记录的写与读、等待、路由与命令行。"""

import copy
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dsflow.cli import app as cli
from dsflow.core.approval import (ApprovalError, approvals_view, decide, parse_record, read_record,
                                  wait_for, withdraw)
from dsflow.core.project import Project
from dsflow.index.db import PlatformIndex
from dsflow.server.app import create_app

from .conftest import S1, write_registry

runner = CliRunner()
STEP_12 = f"{S1}/1.2_清洗"


def touch(root, rel, text="x\n"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def set_status(root, reg, step_id, status, **extra):
    reg = copy.deepcopy(reg)
    s = next(s for s in reg["steps"] if s["id"] == step_id)
    s["status"] = status
    s.update(extra)
    write_registry(root, reg)
    return reg


def status_of(root, step_id):
    raw = json.loads((root / "lifecycle/steps.json").read_text(encoding="utf-8"))
    return next(s["status"] for s in raw["steps"] if s["id"] == step_id)


def loaded(root, readonly=False):
    project = Project(root, readonly=readonly)
    reg, _ = project.load()
    return project, reg


def test_plan_approval_writes_record_and_status(mini_project):
    root, reg = mini_project
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "pending_approval")
    project, model = loaded(root)
    out = decide(project, model, "1.2", "approval", "approve", "可以，按这个做。\n第二行")
    assert (out["from"], out["to"]) == ("pending_approval", "in_progress") and out["warnings"] == []
    assert status_of(root, "1.2") == "in_progress"
    text = (root / STEP_12 / "approval_record.md").read_text(encoding="utf-8")
    assert text.startswith("# 审批记录 · 1.2 清洗\n") and "**原话**：可以，按这个做。 第二行" in text
    entries = parse_record(text)
    assert len(entries) == 1 and entries[0]["decision"] == "approve" and entries[0]["kind"] == "approval"
    assert entries[0]["source"] == "平台" and (entries[0]["from"], entries[0]["to"]) == ("pending_approval", "in_progress")
    assert "plan.md（修改于" in text
    # 注册表别的字段原样保留、缩进不变
    raw = (root / "lifecycle/steps.json").read_text(encoding="utf-8")
    assert '"notes": "测试用"' in raw and raw.startswith('{\n  "title"')


def test_reject_keeps_status_and_appends(mini_project):
    root, reg = mini_project
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "pending_approval")
    project, model = loaded(root)
    decide(project, model, "1.2", "approval", "reject", "范围太大，先只做重复行。")
    assert status_of(root, "1.2") == "pending_approval"
    project, model = loaded(root)
    decide(project, model, "1.2", "approval", "approve", "改过了，可以。", source="命令行")
    entries = read_record(project, next(s for s in model.steps if s.id == "1.2").revisions or [None] and _rev(model, "1.2"))
    assert [e["decision"] for e in entries] == ["reject", "approve"] and entries[1]["source"] == "命令行"


def _rev(model, step_id):
    from dsflow.core.approval import current_revision, find_step

    return current_revision(find_step(model, step_id))


def test_acceptance_confirm_and_reject(mini_project):
    root, reg = mini_project
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    touch(root, f"{STEP_12}/report.md", "# 1.2 报告\n")
    touch(root, f"{STEP_12}/nb_1.2.ipynb", "{}")
    set_status(root, reg, "1.2", "awaiting_acceptance")
    project, model = loaded(root)
    out = decide(project, model, "1.2", "acceptance", "reject", "数字对不上。")
    assert out["to"] == "in_progress" and status_of(root, "1.2") == "in_progress"
    set_status(root, reg, "1.2", "awaiting_acceptance")
    project, model = loaded(root)
    out = decide(project, model, "1.2", "acceptance", "approve", "看懂了，同意。")
    assert out["to"] == "done" and status_of(root, "1.2") == "done"
    assert out["warnings"] and "还没有验收报告" in out["warnings"][0]
    assert "没有验收报告" in (root / STEP_12 / "approval_record.md").read_text(encoding="utf-8")


def test_revision_status_follows(mini_project):
    root, reg = mini_project
    reg = set_status(root, reg, "1.1", "awaiting_acceptance")
    reg["steps"][0]["revisions"][1]["status"] = "awaiting_acceptance"
    write_registry(root, reg)
    project, model = loaded(root)
    decide(project, model, "1.1", "acceptance", "approve", "好。")
    raw = json.loads((root / "lifecycle/steps.json").read_text(encoding="utf-8"))
    assert raw["steps"][0]["status"] == "done" and raw["steps"][0]["revisions"][1]["status"] == "done"
    assert raw["steps"][0]["revisions"][0]["status"] == "partial"


@pytest.mark.parametrize("status,kind,decision,code,text", [
    ("pending", "approval", "approve", 409, "待审批"),
    ("pending_approval", "acceptance", "approve", 409, "待验收"),
    ("pending_approval", "approval", "bogus", 400, "不认识"),
])
def test_guardrails_status(mini_project, status, kind, decision, code, text):
    root, reg = mini_project
    set_status(root, reg, "1.2", status)
    project, model = loaded(root)
    with pytest.raises(ApprovalError) as exc:
        decide(project, model, "1.2", kind, decision, "")
    assert exc.value.status == code and text in str(exc.value)


def test_guardrails_readonly_missing_plan_unknown_step(mini_project):
    root, reg = mini_project
    set_status(root, reg, "1.2", "pending_approval")
    project, model = loaded(root, readonly=True)
    with pytest.raises(ApprovalError) as exc:
        decide(project, model, "1.2", "approval", "approve", "")
    assert exc.value.status == 403
    project, model = loaded(root)
    with pytest.raises(ApprovalError) as exc:
        decide(project, model, "1.2", "approval", "approve", "")
    assert exc.value.status == 409 and "plan.md" in str(exc.value)
    with pytest.raises(ApprovalError) as exc:
        decide(project, model, "9.9", "approval", "approve", "")
    assert exc.value.status == 404
    assert status_of(root, "1.2") == "pending_approval" and not (root / STEP_12 / "approval_record.md").exists()


def test_wait_for_returns_when_decided_and_times_out(mini_project):
    root, reg = mini_project
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "pending_approval")
    project = Project(root, readonly=False)
    assert wait_for(project, "1.2", timeout=0.3, interval=0.1)["result"] == "timeout"

    def later():
        time.sleep(0.4)
        p, m = loaded(root)
        decide(p, m, "1.2", "approval", "approve", "行。")

    threading.Thread(target=later).start()
    got = wait_for(project, "1.2", timeout=5, interval=0.1)
    assert got["result"] == "approved" and got["status"] == "in_progress" and got["entry"]["note"] == "行。"

    set_status(root, reg, "1.2", "pending_approval")

    def later_reject():
        time.sleep(0.3)
        p, m = loaded(root)
        decide(p, m, "1.2", "approval", "reject", "再改改。")

    threading.Thread(target=later_reject).start()
    assert wait_for(project, "1.2", timeout=5, interval=0.1)["result"] == "rejected"


def test_api_routes(mini_project):
    root, reg = mini_project
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "pending_approval")
    client = TestClient(create_app(PlatformIndex()))
    pid = client.post("/api/projects", json={"path": str(root), "readonly": False}).json()["id"]
    base = f"/api/projects/{pid}/steps/1.2/approval"
    view = client.get(base).json()
    assert view["pending"] == "approval" and view["entries"] == [] and view["readonly"] is False
    bad = client.post(base, json={"kind": "acceptance", "decision": "approve", "note": ""})
    assert bad.status_code == 409
    ok = client.post(base, json={"kind": "approval", "decision": "approve", "note": "通过。"})
    assert ok.status_code == 200 and ok.json()["to"] == "in_progress"
    view = client.get(base).json()
    assert view["pending"] is None and len(view["entries"]) == 1 and view["path"].endswith("approval_record.md")
    assert client.get(f"/api/projects/{pid}/steps/1.2").json()["step"]["status"] == "in_progress"
    assert client.get(f"/api/projects/{pid}/steps/9.9/approval").status_code == 404
    ro = client.post("/api/projects", json={"path": str(root), "readonly": True}).json()["id"]
    assert client.post(f"/api/projects/{ro}/steps/1.2/approval", json={"kind": "approval", "decision": "reject"}).status_code == 403


def test_cli_approve_confirm_await(mini_project):
    root, reg = mini_project
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "pending_approval")
    result = runner.invoke(cli, ["approve", str(root), "1.2", "--note", "可以。"])
    assert result.exit_code == 0 and "pending_approval → in_progress" in result.output
    assert runner.invoke(cli, ["approve", str(root), "1.2"]).exit_code == 1  # 已经进行中，没有可批的
    touch(root, f"{STEP_12}/report.md", "# 1.2 报告\n")
    touch(root, f"{STEP_12}/nb_1.2.ipynb", "{}")
    set_status(root, reg, "1.2", "awaiting_acceptance")
    result = runner.invoke(cli, ["confirm", str(root), "1.2", "--note", "同意。"])
    assert result.exit_code == 0 and "→ done" in result.output and "注意：" in result.output
    result = runner.invoke(cli, ["await", str(root), "1.2", "--timeout", "0.2", "--interval", "0.1"])
    assert result.exit_code == 4 and json.loads(result.output.strip().splitlines()[-1])["result"] == "timeout"
    set_status(root, reg, "1.2", "pending_approval")
    result = runner.invoke(cli, ["reject", str(root), "1.2", "--note", "先不做。"])
    assert result.exit_code == 0 and "pending_approval → pending_approval" in result.output
    nxt = json.loads(runner.invoke(cli, ["next", str(root), "--json"]).output)
    assert nxt["phase"] == "await_approval" and nxt["approvals"][-1]["decision"] == "reject"
    assert any(c.startswith("dsflow await . 1.2") for c in nxt["commands"])


# ---------- 撤回填错的审批 ----------

def test_withdraw_undoes_last_decision_and_keeps_the_record(mini_project):
    """撤回：状态回到表态之前，记录不删——多出一条「撤回」，写明撤的是哪一条。"""
    root, reg = mini_project
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "pending_approval")
    project, model = loaded(root)
    decide(project, model, "1.2", "approval", "approve", "可以。")
    assert status_of(root, "1.2") == "in_progress"

    project, model = loaded(root)
    out = withdraw(project, model, "1.2", "点错了，计划还要改")
    assert (out["from"], out["to"]) == ("in_progress", "pending_approval")
    assert status_of(root, "1.2") == "pending_approval"
    assert out["withdrew"]["decision"] == "approve"
    text = (root / STEP_12 / "approval_record.md").read_text(encoding="utf-8")
    assert "· 撤回 · 计划审批（平台）" in text and "**原话**：点错了，计划还要改" in text
    assert "依据：撤回" in text and "的「通过 · 计划审批」" in text
    entries = parse_record(text)
    assert [e["decision"] for e in entries] == ["approve", "withdraw"], "原来那条不会被删掉"
    assert entries[1]["kind"] == "approval" and entries[1]["decision_label"] == "撤回"

    # 撤回之后可以重新表态；连着撤两次不行
    project, model = loaded(root)
    with pytest.raises(ApprovalError):
        withdraw(project, model, "1.2", "再撤一次")
    decide(project, model, "1.2", "approval", "reject", "范围太大。")
    project, model = loaded(root)
    assert withdraw(project, model, "1.2")["to"] == "pending_approval", "退回不改状态，撤回它也不改"


def test_withdraw_refuses_when_the_step_moved_on(mini_project):
    """状态已经不是那条记录留下的样子（agent 接着往下做了），就不许撤。"""
    root, reg = mini_project
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "pending_approval")
    project, model = loaded(root)
    decide(project, model, "1.2", "approval", "approve", "可以。")
    touch(root, f"{STEP_12}/report.md", "# 1.2 报告\n")
    touch(root, f"{STEP_12}/nb_1.2.ipynb", "{}")
    set_status(root, reg, "1.2", "awaiting_acceptance")
    project, model = loaded(root)
    view = approvals_view(project, model, "1.2")
    assert view["can_withdraw"] is False and "待验收" in view["withdraw_blocked"]
    with pytest.raises(ApprovalError):
        withdraw(project, model, "1.2")
    # 只读项目连撤回也不写项目目录
    ro, ro_model = loaded(root, readonly=True)
    assert approvals_view(ro, ro_model, "1.2")["can_withdraw"] is False
    with pytest.raises(ApprovalError):
        withdraw(ro, ro_model, "1.2")


def test_withdraw_makes_the_agent_keep_waiting(mini_project):
    """agent 正在 await：用户表了态又撤回，等于没表态，继续等。"""
    root, reg = mini_project
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "pending_approval")
    project, model = loaded(root)
    decide(project, model, "1.2", "approval", "reject", "先不做。")   # 退回不改状态
    project, model = loaded(root)
    withdraw(project, model, "1.2", "退错了")
    out = wait_for(project, "1.2", "any", timeout=0.3, interval=0.1)
    assert out["result"] == "timeout", "最后一条是撤回，不算表态"

    def later():
        time.sleep(0.3)
        p, m = loaded(root)
        decide(p, m, "1.2", "approval", "approve", "这次是真的通过。")

    threading.Thread(target=later).start()
    got = wait_for(project, "1.2", "any", timeout=5, interval=0.1)
    assert got["result"] == "approved" and got["entry"]["note"] == "这次是真的通过。"


def test_withdraw_api_and_cli(mini_project):
    root, reg = mini_project
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "pending_approval")
    client = TestClient(create_app(PlatformIndex()))
    pid = client.post("/api/projects", json={"path": str(root), "readonly": False}).json()["id"]
    base = f"/api/projects/{pid}/steps/1.2/approval"
    assert client.get(base).json()["can_withdraw"] is False, "还没有记录，没有可撤的"
    client.post(base, json={"kind": "approval", "decision": "approve", "note": "手滑点的。"})
    assert client.get(base).json()["can_withdraw"] is True
    out = client.post(f"{base}/withdraw", json={"note": "点错了"})
    assert out.status_code == 200 and out.json()["to"] == "pending_approval"
    assert client.get(f"/api/projects/{pid}/steps/1.2").json()["step"]["status"] == "pending_approval"
    assert client.post(f"{base}/withdraw", json={"note": "再撤"}).status_code == 409

    result = runner.invoke(cli, ["approve", str(root), "1.2", "--note", "又点了一次。"])
    assert result.exit_code == 0
    result = runner.invoke(cli, ["withdraw", str(root), "1.2", "--note", "还是撤了"])
    assert result.exit_code == 0 and "已撤回" in result.output and "in_progress → pending_approval" in result.output
