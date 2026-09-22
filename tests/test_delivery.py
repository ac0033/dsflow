"""交付（M5）：模型登记与状态门槛、交付清单的生成 / 刷新 / 核对、执行脚本代替 notebook、告警、接口与命令行。"""

import copy
import os
import time

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import dsflow
from dsflow.cli import app as cli
from dsflow.core.project import Project, ProjectError
from dsflow.core.validate import parse_registry, validate_model
from dsflow.delivery.checklist import check_checklist, checklist_rel, draft_checklist, load_checklist, write_checklist
from dsflow.delivery.models import ModelError, ModelStore
from dsflow.index.db import PlatformIndex
from dsflow.progress.alerts import compute_alerts
from dsflow.server.app import create_app
from dsflow.tracking.store import RunStore

from .conftest import REV_11, STEP_11

runner = CliRunner()
MODEL = f"{REV_11}/outputs/model.json"


def train(root, *, mae=12.5, validity="有效", content='{"coef": [0.5]}'):
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "train.csv").write_text("x,y\n1,2\n2,4\n", encoding="utf-8")
    model = root / MODEL
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(content, encoding="utf-8")
    with dsflow.start_run("1.1", project=root, hypothesis="线性模型优于上月值") as run:
        run.log_input("data/train.csv", name="train")
        run.log_metrics({"MAE": mae})
        ref = run.log_model(model, "demand", description="需求量线性模型")
        run.set_conclusion("MAE 低于基线", validity=validity)
    return run, ref


def fill(root, **over):
    """模拟负责人把判断部分填完。"""
    path = root / checklist_rel("demand")
    c = yaml.safe_load(path.read_text(encoding="utf-8"))
    c.update(summary="交付 SKU 月度需求量预测模型", usage=["uv run python predict.py --month 2026-07"],
             applicability={"scope": ["在售 SKU 的下月需求量"], "not_for": ["上架不足 3 个月的 SKU"],
                            "data_period": "2024-07 至 2026-06", "known_weaknesses": []},
             monitoring=[{"metric": "月度 MAE", "threshold": "高于 15", "frequency": "每月", "action": "重新训练并登记新版本"}])
    for m in c["metrics"]:
        m["scope"] = "验证期 SKU×月"
    c.update(over)
    path.write_text(yaml.safe_dump(c, allow_unicode=True, sort_keys=False), encoding="utf-8")


def failed(report):
    return {i["label"] for i in report["items"] if not i["passed"]}


def test_log_model_registers_candidate_linked_to_run(mini_project):
    root, _ = mini_project
    run, ref = train(root)
    project = Project(root, readonly=False)
    store = ModelStore(project)
    v = store.get("demand", ref["version"])
    assert v["status"] == "candidate" and v["step"] == "1.1" and v["run_id"] == run.run_id
    assert v["run"]["metrics"] == {"MAE": 12.5} and v["run"]["inputs"][0]["name"] == "train"
    assert RunStore(project).get(run.run_id)["models"] == [ref]
    again = store.register(MODEL, "demand")
    assert again["created"] is False and again["version"]["version"] == ref["version"]
    assert again["version"]["run_id"] == run.run_id  # 没给运行时不改关联
    rerun, same = train(root)  # 重新训练得到同样内容：仍是候选，关联改为最新运行
    v = store.get("demand", same["version"])
    assert same["version"] == ref["version"] and v["run_id"] == rerun.run_id and len(v["history"]) == 2
    store.promote("demand", ref["version"], "accepted", "验收通过")
    third, _ = train(root)
    assert store.get("demand", ref["version"])["run_id"] == rerun.run_id  # 已验收的不再改关联
    with pytest.raises(ModelError):
        store.register(MODEL, "坏/名字")
    with pytest.raises(ModelError):
        store.register(MODEL, "demand2", run_id="不存在的运行")


def test_promotion_requires_valid_run_and_checklist(mini_project):
    root, _ = mini_project
    _, ref = train(root, validity="无结论")
    store = ModelStore(Project(root, readonly=False))
    with pytest.raises(ModelError, match="有效"):
        store.promote("demand", ref["version"], "accepted", "验收通过")
    with pytest.raises(ModelError, match="理由"):
        store.promote("demand", ref["version"], "accepted", " ")
    with pytest.raises(ModelError, match="不能从"):
        store.promote("demand", ref["version"], "delivered", "直接交付")
    _, ref2 = train(root, content='{"coef": [0.6]}')  # 结论有效的另一次训练：新版本
    v = store.promote("demand", ref2["version"], "accepted", "MAE 低于基线，验收通过")
    assert v["status"] == "accepted" and [h["status"] for h in v["history"]] == ["candidate", "accepted"]
    gates = {g["code"]: g for g in store.gates(v, "delivered")}
    assert not gates["code"]["passed"] and not gates["code"]["blocking"]  # 不是 git 仓库：提示，不拦
    assert gates["step"]["passed"] and not gates["checklist"]["passed"]
    with pytest.raises(ModelError, match="交付清单"):
        store.promote("demand", ref2["version"], "delivered", "交付")
    assert store.promote("demand", ref2["version"], "candidate", "撤回验收：发现数据泄漏")["status"] == "candidate"


def test_checklist_draft_refresh_and_check(mini_project):
    root, _ = mini_project
    _, ref = train(root)
    project = Project(root, readonly=False)
    v = ModelStore(project).get("demand", ref["version"])
    assert write_checklist(project, draft_checklist(project, v)) == "delivery/demand/checklist.yaml"
    report = check_checklist(project, v)
    assert not report["complete"] and {"一句话说明", "没有「待填」", "监控方案", "指标口径"} <= failed(report)
    assert {"对应本模型版本", "复现入口", "训练数据版本与产出运行一致", "指标数值与产出运行一致", "产物文件都在"}.isdisjoint(failed(report))
    assert any(ref["version"] in cmd or v["sha256"] in cmd for cmd in report["checklist"]["reproduce"])
    fill(root)
    report = check_checklist(project, v)
    assert report["complete"], report["items"]
    assert "部署方式待定" in report["notes"]
    existing, _ = load_checklist(project, "demand")
    refreshed = draft_checklist(project, v, existing)  # 刷新：事实部分重写，人写的部分保留
    assert refreshed["summary"] == "交付 SKU 月度需求量预测模型" and refreshed["metrics"][0]["scope"] == "验证期 SKU×月"
    fill(root, metrics=[{"name": "MAE", "value": 11.0, "scope": "验证期"}])
    assert "指标数值与产出运行一致" in failed(check_checklist(project, v))
    fill(root, version="000000000000")
    assert "对应本模型版本" in failed(check_checklist(project, v))
    fill(root, artifacts=[{"path": "outputs/nope.bin", "purpose": "不存在"}])
    assert "产物文件都在" in failed(check_checklist(project, v))
    with pytest.raises(ProjectError):
        write_checklist(Project(root, readonly=True), refreshed)


def test_deliver_then_alerts(mini_project):
    root, _ = mini_project
    _, ref = train(root)
    project = Project(root, readonly=False)
    store = ModelStore(project)
    ver = ref["version"]
    store.promote("demand", ver, "accepted", "验收通过")
    write_checklist(project, draft_checklist(project, store.get("demand", ver)))
    fill(root)
    assert store.promote("demand", ver, "delivered", "清单齐全，交付")["status"] == "delivered"
    reg, issues = project.load()

    def codes():
        return {a["code"]: a for a in compute_alerts(project, reg, issues, RunStore(project).list())}

    assert not {c for c in codes() if c.startswith(("model", "checklist"))}
    (root / MODEL).write_text('{"coef": [9.9]}', encoding="utf-8")  # 覆盖已交付的模型文件
    assert codes()["model_changed"]["level"] == "serious"
    fill(root, summary="待填")
    assert codes()["checklist_incomplete"]["level"] == "warning"
    for _ in range(30):  # Windows 上刚写过的文件可能被扫描程序短暂占用
        try:
            (root / MODEL).unlink()
            break
        except PermissionError:
            time.sleep(0.1)
    assert codes()["model_missing"]["link"] == f"models/demand/{ver}"


def test_stale_report_is_info_when_card_numbers_still_match(mini_project):
    root, _ = mini_project
    out = root / REV_11 / "outputs"
    out.mkdir(parents=True)
    (out / "clean.csv").write_text("a\n1\n2\n3\n", encoding="utf-8")
    card = {"step": "1.1", "headline": "测试", "core_numbers": [{"label": "行数", "after": 3, "source": "outputs/clean.csv#rows"}]}
    (root / REV_11 / "step_card.yaml").write_text(yaml.safe_dump(card, allow_unicode=True), encoding="utf-8")
    old = time.time() - 3600
    os.utime(root / REV_11 / "acceptance" / "report.md", (old, old))
    project = Project(root, readonly=False)
    store = RunStore(project)
    store.finish(store.create("1.1")["run_id"], "succeeded", exit_code=0)
    reg, issues = project.load()

    def stale():
        return next(a for a in compute_alerts(project, reg, issues, store.list()) if a["code"] == "report_stale")

    assert stale()["level"] == "info" and "1 个带出处的数字" in stale()["message"]
    (out / "clean.csv").write_text("a\n1\n2\n", encoding="utf-8")
    assert stale()["level"] == "warning" and "不一致" in stale()["message"]


def test_execution_scripts_replace_notebook(mini_project):
    root, reg = mini_project
    reg = copy.deepcopy(reg)
    (root / STEP_11 / "nb_1.1.ipynb").unlink()
    assert any(i.code == "notebook" for i in validate_model(parse_registry(reg)[0], root))
    reg["steps"][0]["execution_scripts"] = [f"{STEP_11}/src/run.py"]
    assert any(i.code == "script" for i in validate_model(parse_registry(reg)[0], root))
    (root / STEP_11 / "src").mkdir()
    (root / STEP_11 / "src" / "run.py").write_text("print(1)\n", encoding="utf-8")
    assert not [i for i in validate_model(parse_registry(reg)[0], root) if i.severity == "error"]


def test_api_models(mini_project):
    root, _ = mini_project
    _, ref = train(root)
    ver = ref["version"]
    client = TestClient(create_app(PlatformIndex()))
    pid = client.post("/api/projects", json={"path": str(root), "readonly": False}).json()["id"]
    base = f"/api/projects/{pid}/models"
    assert client.get(base).json()["models"][0]["versions"][0]["version"] == ver
    d = client.get(f"{base}/demand/{ver}").json()
    assert d["target"] == "accepted" and {"run", "validity", "file"} <= {g["code"] for g in d["gates"]}
    assert d["checklist"]["exists"] is False
    assert client.get(f"{base}/demand/nope").status_code == 404
    assert client.post(f"{base}/demand/{ver}/status", json={"to": "delivered", "note": "x"}).status_code == 400
    assert client.post(f"{base}/demand/{ver}/status", json={"to": "accepted", "note": "验收通过"}).json()["status"] == "accepted"
    c = client.post(f"{base}/demand/{ver}/checklist").json()
    assert c["exists"] and not c["complete"] and (root / checklist_rel("demand")).is_file()
    other = client.post(base, json={"path": MODEL, "name": "demand_copy"})
    assert other.status_code == 201 and other.json()["version"]["run_id"] is None
    assert client.post(base, json={"path": "missing.bin", "name": "x"}).status_code == 404
    ro = client.post("/api/projects", json={"path": str(root), "readonly": True}).json()["id"]
    ro_base = f"/api/projects/{ro}/models"
    assert client.post(ro_base, json={"path": MODEL, "name": "demand"}).status_code == 201  # 只读：登记在平台目录
    assert client.post(f"{ro_base}/demand/{ver}/checklist").status_code == 403


def test_cli_model_delivery_and_check(mini_project):
    root, _ = mini_project
    _, ref = train(root)
    ver = ref["version"]
    listed = runner.invoke(cli, ["model", "list", str(root)])
    assert listed.exit_code == 0 and ver in listed.output and "候选" in listed.output
    assert "内容未变" in runner.invoke(cli, ["model", "add", str(root), MODEL, "--name", "demand"]).output
    assert runner.invoke(cli, ["model", "promote", str(root), "demand", ver, "--to", "delivered", "--note", "x"]).exit_code == 1
    assert runner.invoke(cli, ["model", "promote", str(root), "demand", ver, "--to", "accepted", "--note", "验收通过"]).exit_code == 0
    init = runner.invoke(cli, ["delivery", "init", str(root), "demand"])
    assert init.exit_code == 0 and "已生成" in init.output and "未通过" in init.output
    assert runner.invoke(cli, ["delivery", "check", str(root), "demand"]).exit_code == 1
    fill(root)
    assert runner.invoke(cli, ["delivery", "check", str(root), "demand"]).exit_code == 0
    again = runner.invoke(cli, ["delivery", "init", str(root), "demand"])
    assert "已刷新" in again.output and "交付 SKU" in (root / checklist_rel("demand")).read_text(encoding="utf-8")
    assert runner.invoke(cli, ["model", "promote", str(root), "demand", ver, "--to", "delivered", "--note", "交付"]).exit_code == 0
    ok = runner.invoke(cli, ["check", str(root)])
    assert ok.exit_code == 0, ok.output
    (root / MODEL).write_text('{"coef": [7.7]}', encoding="utf-8")
    bad = runner.invoke(cli, ["check", str(root)])
    assert bad.exit_code == 1 and "模型 demand" in bad.output
