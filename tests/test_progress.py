"""进度与核对：问题/决策/待决事项、项目文件里的待决事项、告警（含故障注入）、数字与术语核对、停止规则、知识边界、活动流、接口。"""

import copy
import json
import os
import time

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from dsflow.core.project import Project
from dsflow.core.validate import parse_registry
from dsflow.data.datasets import DatasetStore
from dsflow.data.engine import DataError
from dsflow.index.db import PlatformIndex
from dsflow.progress.alerts import compute_alerts
from dsflow.progress.checks import check_terms, parse_number, step_checks
from dsflow.progress.knowledge import direction, stop_rules
from dsflow.progress.tracker import TrackerError, TrackerStore, project_pending
from dsflow.server.app import create_app
from dsflow.tracking.store import RunStore

from .conftest import REV_11, STEP_11, write_registry


def model(root):
    reg, issues = Project(root).load()
    return reg, issues


# ---------- 问题 / 决策 / 待决事项 ----------

def test_tracker_crud_and_readonly_location(mini_project, isolated_home):
    root, _ = mini_project
    store = TrackerStore(Project(root, readonly=True))
    q = store.create("issues", {"title": "2024-03 有负金额", "step": "1.1", "severity": "高", "blocking": True})
    assert q["id"] == "Q1" and q["status"] == "open" and q["created_at"]
    done = store.update("issues", "Q1", {"status": "resolved", "note": "业务确认是退货"})
    assert done["resolved_at"] and done["note"] == "业务确认是退货"
    assert store.update("issues", "Q1", {"status": "open"})["resolved_at"] is None
    j = store.create("decisions", {"title": "缺失金额不当 0", "decision": "标记为金额未知", "rejected": ["按 0 处理"]})
    assert j["id"] == "J1" and j["date"]
    p = store.create("pending", {"question": "有效状态集合如何定义？", "blocking": True})
    assert p["id"] == "P1" and store.create("pending", {"question": "第二个"})["id"] == "P2"
    with pytest.raises(TrackerError):
        store.create("decisions", {"title": "缺决策内容"})
    with pytest.raises(TrackerError):
        store.list("unknown")
    assert store.delete("pending", "P2") and not store.delete("pending", "P9")
    assert not (root / ".dsflow").exists() and (isolated_home / "projects").is_dir()  # 只读项目写平台目录


def test_project_pending_prefers_current_revision(mini_project):
    root, reg = mini_project
    content = {"schema_version": "1", "待决事项": [
        {"id": "D1", "问题": "目标用金额还是销量？", "推荐答案": "金额", "依据": "可加", "影响范围": "目标", "是否阻塞后续执行": True, "状态": "unresolved"},
        {"id": "D2", "问题": "已裁定的事", "是否阻塞后续执行": False, "状态": "resolved"},
    ]}
    old = root / STEP_11 / "outputs" / "decisions_required.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"待决事项": [{"id": "OLD", "问题": "旧轮次"}]}, ensure_ascii=False), encoding="utf-8")
    cur = root / REV_11 / "outputs" / "decisions_required.json"
    cur.parent.mkdir(parents=True)
    cur.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    items = project_pending(root, parse_registry(reg)[0])
    assert [i["id"] for i in items] == ["D1", "D2"] and items[0]["revision"] == "r02"
    assert items[0]["blocking"] and items[0]["recommendation"] == "金额" and items[1]["status"] == "resolved"


# ---------- 告警（故障注入） ----------

@pytest.fixture
def alert_project(mini_project):
    root, reg = mini_project
    (root / "data").mkdir()
    (root / "data" / "raw.csv").write_text("id,v\n1,2\n", encoding="utf-8")
    DatasetStore(Project(root, readonly=False)).register(
        "data/raw.csv", "raw", "raw", description="一行 = 一条原始记录，业务系统导出，1.1 清洗后进主数据")
    return root, reg


def codes(root, runs=None, verify=False):
    reg, issues = model(root)
    return {a["code"]: a for a in compute_alerts(Project(root, readonly=False), reg, issues, runs or [], verify)}


def test_no_alerts_on_clean_project(alert_project):
    root, _ = alert_project
    assert set(codes(root)) == set()


def test_dataset_without_own_description_is_warned(alert_project):
    """数据里文件名下面那行小字：没写、或几份数据共用同一句，都要报出来。"""
    root, _ = alert_project
    project = Project(root, readonly=False)
    store = DatasetStore(project)
    (root / "data" / "copy.csv").write_text("id,v\n1,2\n", encoding="utf-8")
    store.register("data/copy.csv", "copy", "processed", require_description=False)  # run.log_input 走的就是这条路
    assert codes(root)["dataset_no_description"]["level"] == "warning"
    store.describe("copy", "一行 = 一条原始记录，业务系统导出，1.1 清洗后进主数据")  # 和 raw 的介绍一模一样
    assert codes(root)["dataset_same_description"]["level"] == "warning"
    store.describe("copy", "一行 = 一条清洗后的记录，1.1 从原始记录去掉空标题后得到，2.1 做质量分析用")
    assert "dataset_no_description" not in codes(root) and "dataset_same_description" not in codes(root)
    with pytest.raises(DataError):
        store.describe("copy", "   ")
    with pytest.raises(DataError):
        store.describe("没登记过的表", "一句话")


def test_raw_data_change_is_critical(alert_project):
    root, _ = alert_project
    path = root / "data" / "raw.csv"
    path.write_text("id,v\n1,3\n", encoding="utf-8")  # 同样大小，内容变了
    os.utime(path, (time.time() + 5, time.time() + 5))
    maybe = codes(root)
    assert maybe["raw_maybe_changed"]["level"] == "critical"
    assert codes(root, verify=True)["raw_changed"]["level"] == "critical"
    path.write_text("id,v\n1,2\n", encoding="utf-8")  # 改回原内容：核对哈希后不再告警
    os.utime(path, (time.time() + 9, time.time() + 9))
    assert "raw_changed" not in codes(root, verify=True) and "raw_maybe_changed" not in codes(root, verify=True)
    path.unlink()
    assert codes(root)["raw_missing"]["level"] == "critical"


def test_status_and_run_alerts(alert_project):
    root, reg = alert_project
    reg = copy.deepcopy(reg)
    reg["steps"][0]["revisions"][1]["status"] = "partial"  # 步骤标为已完成，当前轮次却是部分完成
    write_registry(root, reg)
    store = RunStore(Project(root, readonly=False))
    store.finish(store.create("1.1")["run_id"], "failed", exit_code=2, error="命令退出码 2")
    got = codes(root, store.list())
    assert got["status_mismatch"]["level"] == "serious" and "r02" in got["status_mismatch"]["message"]
    assert got["run_failed"]["step"] == "1.1"


def test_report_older_than_latest_run(alert_project):
    root, _ = alert_project
    report = root / REV_11 / "report.md"
    report.write_text("# 1.1 报告\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(report, (old, old))
    (root / REV_11 / "acceptance" / "report.md").touch()
    os.utime(root / REV_11 / "acceptance" / "report.md", (old, old))
    store = RunStore(Project(root, readonly=False))
    store.finish(store.create("1.1")["run_id"], "succeeded", exit_code=0)
    assert "report_stale" in codes(root, store.list())


def test_done_without_acceptance(mini_project):
    root, reg = mini_project
    reg = copy.deepcopy(reg)
    reg["steps"][0].pop("acceptance_report")
    (root / REV_11 / "acceptance" / "report.md").unlink()
    write_registry(root, reg)
    assert "no_acceptance" in codes(root)


# ---------- 数字与术语核对 ----------

@pytest.mark.parametrize("raw,expected", [
    (118170, (118170.0, 0)), ("1,830", (1830.0, 0)), ("43.1%", (0.431, 3)), (0.431, (0.431, 3)), ("不是数", None), (None, None),
])
def test_parse_number(raw, expected):
    got = parse_number(raw)
    assert got == expected or (got and expected and got[1] == expected[1] and abs(got[0] - expected[0]) < 1e-12)


def test_card_numbers_are_recomputed(mini_project):
    root, reg = mini_project
    out = root / REV_11 / "outputs"
    out.mkdir()
    pd.DataFrame({"处理": ["原始", "清洗后"], "行数": [120000, 118170]}).to_csv(out / "ledger.csv", index=False)
    pd.DataFrame({"金额": [1.25, 2.5, None]}).to_parquet(out / "clean.parquet", index=False)
    (out / "summary.json").write_text(json.dumps({"rows": {"after": 3}}), encoding="utf-8")
    card = {"step": "1.1", "headline": "测试", "core_numbers": [
        {"label": "清洗后行数", "after": "118,170", "source": "outputs/ledger.csv#sql:SELECT 行数 FROM data WHERE 处理 = '清洗后'"},
        {"label": "明细行数", "after": 3, "source": "outputs/clean.parquet#rows"},
        {"label": "金额合计", "after": 3.8, "source": "outputs/clean.parquet#sum:金额"},  # 实际 3.75，写成一位小数：四舍五入后一致
        {"label": "JSON 取值", "after": 3, "source": f"{REV_11}/outputs/summary.json#/rows/after"},  # 按项目根目录解析
        {"label": "写错的数", "after": 118000, "source": "outputs/ledger.csv#sql:SELECT 行数 FROM data WHERE 处理 = '清洗后'"},
        {"label": "没出处", "after": 1},
        {"label": "出处不存在", "after": 1, "source": "outputs/nope.csv#rows"},
    ]}
    (root / REV_11 / "step_card.yaml").write_text(yaml.safe_dump(card, allow_unicode=True), encoding="utf-8")
    r = step_checks(Project(root, readonly=False), parse_registry(reg)[0], "1.1")
    status = {n["label"]: n["status"] for n in r["numbers"]["items"]}
    assert status == {"清洗后行数": "match", "明细行数": "match", "金额合计": "match", "JSON 取值": "match",
                      "写错的数": "mismatch", "没出处": "no_source", "出处不存在": "error"}
    assert (r["numbers"]["checked"], r["numbers"]["matched"], r["numbers"]["total"]) == (5, 4, 7)


def test_terms():
    vocab = [{"term": "SPU", "meaning": "标准产品单元", "source": "商品表", "avoid": ["商品父级"]}, {"term": "订单行", "meaning": "", "source": ""}]
    r = check_terms("**结论**：商品父级之后才上传；**SPU上传时间**与**商品父级**，**订单行**不变，**新造概念**，**这是一句很长的话，不算术语**", vocab)
    assert r["avoid"] == [{"found": "商品父级", "use": "SPU", "count": 2}]
    assert r["unregistered"] == ["新造概念"]


# ---------- 停止规则与知识边界 ----------

def _run(i, value, metric="MAE", step="6.1", validity="有效", status="succeeded"):
    return {"run_id": f"r{i}", "step": step, "started_at": f"2026-09-15T10:0{i}:00", "status": status,
            "metrics": {metric: value}, "validity": validity, "hypothesis": f"h{i}"}


def test_stop_rule_triggers_only_when_recent_gains_are_small():
    small = stop_rules([_run(1, 100), _run(2, 90), _run(3, 89.5), _run(4, 89.4), _run(5, 89.3)], {})
    assert small[0]["level"] == "stop" and "都不到 1%" in small[0]["hint"]
    assert small[0]["points"][1]["gain"] == pytest.approx(0.1) and small[0]["points"][-1]["best"] == 89.3
    leaky = stop_rules([_run(1, 100), _run(2, 90), _run(3, 1, validity="无效"), _run(4, 89.5), _run(5, 89.4), _run(6, 89.3)], {})
    assert len(leaky[0]["points"]) == 5 and leaky[0]["points"][-1]["best"] == 89.3  # 无效运行的 1 不算最好成绩
    still = stop_rules([_run(1, 100), _run(2, 99.5), _run(3, 99.4), _run(4, 80)], {})
    assert still[0]["level"] == "continue"
    few = stop_rules([_run(1, 100), _run(2, 99)], {})
    assert few[0]["level"] == "insufficient"
    unknown = stop_rules([_run(1, 1, "某指标"), _run(2, 2, "某指标")], {})
    assert unknown[0]["level"] == "unknown"
    assert stop_rules([_run(1, 0.7, "某指标"), _run(2, 0.8, "某指标")], {"某指标": "max"})[0]["direction"] == "max"
    assert direction("AUC", {}) == "max" and direction("验证集误差", {}) == "min"


def test_api_board_tracker_checks_knowledge(alert_project):
    root, _ = alert_project
    store = RunStore(Project(root, readonly=False))
    run = store.create("1.1", hypothesis="试一个方向")
    run["validity"] = "无结论"
    store.save(run)
    store.finish(run["run_id"], "succeeded", exit_code=0)
    client = TestClient(create_app(PlatformIndex()))
    pid = client.post("/api/projects", json={"path": str(root), "readonly": False}).json()["id"]
    base = f"/api/projects/{pid}"
    assert client.post(f"{base}/tracker/issues", json={"title": "负金额", "severity": "高"}).status_code == 201
    assert client.post(f"{base}/tracker/pending", json={"question": "有效状态？", "blocking": True}).status_code == 201
    assert client.post(f"{base}/tracker/decisions", json={"title": "缺决策"}).status_code == 400
    assert client.patch(f"{base}/tracker/issues/Q9", json={"status": "resolved"}).status_code == 404
    board = client.get(f"{base}/board").json()
    assert board["tracker_counts"] == {"open_issues": 1, "decisions": 0, "unresolved_pending": 1}
    assert board["attention"]["blocking_decisions"][0]["question"] == "有效状态？"
    assert {e["kind"] for e in board["activity"]} >= {"run", "issue"}
    assert board["iterations"][0]["invalid"] == 1 and board["stages"][0]["done"] == 1
    assert client.post(f"{base}/board/verify").status_code == 200
    k = client.get(f"{base}/knowledge").json()
    assert k["exploration"][0]["validity"] == "无结论" and k["open_questions"][0]["question"] == "有效状态？"
    assert client.get(f"{base}/steps/1.1/checks").json()["has_card"] is False
    assert len(client.get(f"{base}/checks").json()) == 3


def test_done_without_guide(mini_project):
    root, _ = mini_project
    (root / REV_11 / "guide.yaml").unlink()
    got = codes(root)
    assert got["no_guide"]["level"] == "warning" and got["no_guide"]["step"] == "1.1"
