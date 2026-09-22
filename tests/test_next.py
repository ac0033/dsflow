"""dsflow next：按注册表状态和本轮目录里的文件，判断项目在哪一步、缺什么、下一步做什么。"""

import copy
import json

from typer.testing import CliRunner

from dsflow.cli import app as cli
from dsflow.core.next import focus_step, next_action
from dsflow.core.project import Project

from .conftest import S1, write_registry

runner = CliRunner()
STEP_12 = f"{S1}/1.2_清洗"


def action(root, step=None):
    project = Project(root, readonly=False)
    reg, issues = project.load()
    return next_action(project, reg, issues, step)


def touch(root, rel, text="x\n"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def set_status(root, reg, step_id, status):
    reg = copy.deepcopy(reg)
    next(s for s in reg["steps"] if s["id"] == step_id)["status"] = status
    write_registry(root, reg)
    return reg


def test_focus_prefers_active_then_first_pending(mini_project):
    root, reg = mini_project
    a = action(root)
    assert a["step"]["id"] == "1.2" and a["phase"] == "plan" and a["attention"]["pending_approval"] == []
    assert any("pending_approval" in line for line in a["todo"])
    reg = set_status(root, reg, "2.1", "in_progress")
    assert action(root)["step"]["id"] == "2.1"
    reg = set_status(root, reg, "1.2", "pending_approval")
    a = action(root)
    assert a["step"]["id"] == "1.2" and a["phase"] == "await_approval" and a["missing"] == ["plan.md"]
    assert [x["id"] for x in a["attention"]["pending_approval"]] == ["1.2"]
    assert [x["id"] for x in a["attention"]["in_progress"]] == ["2.1"]


def test_execute_lists_missing_execution_files(mini_project):
    root, reg = mini_project
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "in_progress")
    a = action(root)
    assert a["phase"] == "execute"
    assert a["missing"] == ["nb_<步骤>.ipynb", "report.md", "step_card.yaml", "guide.yaml"]
    assert a["files"]["plan"] == f"{STEP_12}/plan.md" and a["files"]["guide"] is None
    assert any(c.startswith("dsflow run 1.2") for c in a["commands"]) and a["issues"] == []
    touch(root, f"{STEP_12}/nb_1.2.ipynb", "{}")
    touch(root, f"{STEP_12}/report.md", "# 1.2 报告\n")
    touch(root, f"{STEP_12}/step_card.yaml", 'step: "1.2"\nheadline: 清洗完成。\n')
    touch(root, f"{STEP_12}/guide.yaml", 'step: "1.2"\nbrief:\n  question: 删了什么\n  answer: 删了重复行。\n')
    assert action(root)["missing"] == []


def test_acceptance_then_confirmation(mini_project):
    root, reg = mini_project
    touch(root, f"{STEP_12}/plan.md", "# 1.2 计划\n")
    set_status(root, reg, "1.2", "awaiting_acceptance")
    a = action(root)
    assert a["phase"] == "acceptance" and a["missing"] == ["acceptance.md"]
    assert a["commands"][0] == "dsflow guide check . --step 1.2"
    touch(root, f"{STEP_12}/acceptance.md", "# 1.2 验收\n")
    a = action(root)
    assert a["phase"] == "await_confirmation" and a["missing"] == []
    assert a["files"]["acceptance_report"] == f"{STEP_12}/acceptance.md"
    assert [x["id"] for x in a["attention"]["awaiting_acceptance"]] == ["1.2"]


def test_registered_acceptance_report_counts(mini_project):
    root, reg = mini_project
    a = action(root, "1.1")
    assert a["phase"] == "next_step" and a["step"]["revision"] == "r02"
    assert a["files"]["acceptance_report"].endswith("acceptance/report.md") and a["files"]["guide"].endswith("guide.yaml")


def test_missing_plan_is_reported_as_issue(mini_project):
    root, reg = mini_project
    set_status(root, reg, "1.2", "in_progress")
    a = action(root)
    assert a["phase"] == "execute" and any(i["code"] == "missing_file" for i in a["issues"])


def test_all_done_and_unknown_step(mini_project):
    root, reg = mini_project
    reg = copy.deepcopy(reg)
    for s in reg["steps"]:
        s["status"] = "done"
    for s in reg["steps"][1:]:
        touch(root, f"{s['dir']}/plan.md", "# 计划\n")
        touch(root, f"{s['dir']}/report.md", f"# {s['id']} 报告\n")
        touch(root, f"{s['dir']}/nb_{s['id']}.ipynb", "{}")
    write_registry(root, reg)
    a = action(root)
    assert a["step"] is None and a["phase"] == "all_done"
    project = Project(root, readonly=False)
    model, _ = project.load()
    assert focus_step(model) is None
    try:
        focus_step(model, "9.9")
    except KeyError as exc:
        assert exc.args[0] == "9.9"
    else:
        raise AssertionError("未知步骤应当报错")


def test_cli_next_human_and_json(mini_project):
    root, _ = mini_project
    result = runner.invoke(cli, ["next", str(root)])
    assert result.exit_code == 0 and "1.2 清洗" in result.output and "写计划" in result.output
    result = runner.invoke(cli, ["next", str(root), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["phase"] == "plan" and data["project"]["readonly"] is False
    assert runner.invoke(cli, ["next", str(root), "--step", "9.9"]).exit_code == 1
