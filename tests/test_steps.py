"""步骤工作区：文件角色分类、轮次与日期、说明卡、实际推进路径、血缘与接口。"""

import copy
import shutil

import pytest
from fastapi.testclient import TestClient

from dsflow.core.lifecycle import build_graph
from dsflow.core.project import Project
from dsflow.core.steps import actual_path, classify, step_detail
from dsflow.core.validate import parse_registry
from dsflow.data.datasets import DatasetStore
from dsflow.index.db import PlatformIndex
from dsflow.paths import REPO_ROOT
from dsflow.server.app import create_app

from .conftest import REV_11, STEP_11, write_registry


@pytest.mark.parametrize("rel,kind", [
    ("plan.md", "plan"), ("plan_user.md", "plan_user"), ("approval_record.md", "approval"),
    ("planning/approval_record.md", "approval"), ("report.md", "report"), ("user-report.qmd", "report"),
    ("execution_record.md", "execution_record"), ("nb_1.3.ipynb", "notebook"), ("src/build.py", "code"),
    ("acceptance/2026-09-09_主验收/report.md", "acceptance_report"), ("acceptance/report.md", "acceptance_report"),
    ("acceptance/2026-09-09_主验收/src/review.py", "acceptance_code"),
    ("acceptance/2026-09-09_主验收/outputs/x.json", "acceptance_material"),
    ("operations/原1.12_品牌/report.md", "operation"), ("operations/原1.12_品牌/nb_1.12.ipynb", "notebook"),
    ("outputs/issues.csv", "output"), ("reporting/bundle.json", "evidence"), ("step_card.yaml", "card"),
    ("acceptance.md", "acceptance_report"), ("guide.yaml", "guide"),
    ("checks/acceptance.md", "doc"), ("outputs/guide.yaml", "output"),
    ("notes.md", "doc"), ("data.bin", "other"),
])
def test_classify(rel, kind):
    assert classify(rel) == kind


def detail(root, reg, step="1.1"):
    model, issues = parse_registry(reg)
    return step_detail(root, model, step, issues)


def test_revisions_files_and_dates(mini_project):
    root, reg = mini_project
    d = detail(root, reg)
    r01, r02 = d["revisions"]
    assert [r["id"] for r in d["revisions"]] == ["r01", "r02"] and r02["is_current"] and not r01["is_current"]
    kinds01 = {f["rel"]: f["kind"] for f in r01["files"]}
    assert kinds01 == {"plan.md": "plan", "report.md": "report", "nb_1.1.ipynb": "notebook"}  # 不含 revisions/ 下的轮次
    assert r02["acceptance_reports"] == [f"{REV_11}/acceptance/report.md"]
    assert (r02["date"], r02["date_source"]) == ("2026-09-15", "目录名")
    assert r01["date_source"] == "文件修改时间（推断）"
    assert d["dependencies_out"] == [{"step": "1.2", "label": "字段清单"}] and len(d["revision_loops"]) == 1


def test_step_card_parsed_and_errors_reported(mini_project):
    root, reg = mini_project
    shutil.copy(REPO_ROOT / "templates" / "step_card.yaml", root / REV_11 / "step_card.yaml")
    card = detail(root, reg)["revisions"][1]["card"]
    assert card["headline"].startswith("订单清洗已完成") and card["core_numbers"][0]["after"] == 118170
    node = build_graph(parse_registry(reg)[0], root)["nodes"][0]
    assert node["card"]["headline"] == card["headline"] and len(node["card"]["numbers"]) <= 3
    (root / REV_11 / "step_card.yaml").write_text("step: 1.1\ncore_numbers: 不是列表\n", encoding="utf-8")
    bad = detail(root, reg)["revisions"][1]
    assert bad["card"] is None and "无法解析" in bad["card_error"]


def test_actual_path_shows_jump_back(mini_project):
    root, reg = mini_project
    reg = copy.deepcopy(reg)
    reg["steps"][0]["revisions"][0]["date"] = "2026-09-01"
    reg["steps"][1].update(status="done", revisions=[{"id": "r01", "status": "done", "dir": reg["steps"][1]["dir"], "date": "2026-09-05"}],
                           current_revision="r01", execution_notebooks=[])
    reg["steps"][1].pop("execution_notebooks")
    path = actual_path(root, parse_registry(reg)[0])
    assert [(e["step"], e["revision"]) for e in path[:3]] == [("1.1", "r01"), ("1.2", "r01"), ("1.1", "r02")]
    assert path[0]["date_source"] == "注册表"


def test_unknown_step_raises(mini_project):
    root, reg = mini_project
    with pytest.raises(KeyError):
        detail(root, reg, "9.9")


def test_lineage_links_datasets_through_steps(tmp_path):
    root = tmp_path / "p"
    (root / "data").mkdir(parents=True)
    write_registry(root, {"title": "t", "stages": [{"id": 1, "name": "预处理", "dir": "steps/01"}], "steps": [], "dependencies": []})
    for name in ("a.csv", "b.csv", "c.csv"):
        (root / "data" / name).write_text("x\n1\n", encoding="utf-8")
    (root / "data" / "b.csv").write_text("x\n2\n", encoding="utf-8")
    (root / "data" / "c.csv").write_text("x\n3\n", encoding="utf-8")
    store = DatasetStore(Project(root, readonly=False))
    store.register("data/a.csv", "raw", "raw", description="一行 = 一个原始订单行")
    store.register("data/b.csv", "clean", "processed", parents=["raw"], produced_by="1.2",
                   description="一行 = 一个清洗后的订单行")
    store.register("data/c.csv", "feat", "features", parents=["clean", "external"],
                   description="一行 = 一个 SKU 的一个月")
    g = store.lineage()
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"d:raw", "d:clean", "d:feat", "d:external", "s:1.2"}
    assert {(e["from"], e["to"]) for e in g["edges"]} == {("s:1.2", "d:clean"), ("d:raw", "s:1.2"), ("d:clean", "d:feat"), ("d:external", "d:feat")}
    assert next(n for n in g["nodes"] if n["id"] == "d:external")["missing"] is True


def test_step_and_raw_file_api(mini_project):
    root, _ = mini_project
    (root / STEP_11 / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    client = TestClient(create_app(PlatformIndex()))
    pid = client.post("/api/projects", json={"path": str(root)}).json()["id"]
    d = client.get(f"/api/projects/{pid}/steps/1.1").json()
    assert d["step"]["status_label"] == "已完成" and len(d["revisions"]) == 2
    assert client.get(f"/api/projects/{pid}/steps/9.9").status_code == 404
    img = client.get(f"/api/projects/{pid}/file/raw", params={"path": f"{STEP_11}/chart.png"})
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and "script" not in img.headers["content-security-policy"].replace("default-src 'none'", "")
    assert client.get(f"/api/projects/{pid}/file/raw", params={"path": f"{STEP_11}/plan.md"}).status_code == 400
    graph = client.get(f"/api/projects/{pid}").json()["graph"]
    assert [e["step"] for e in graph["path"]].count("1.1") == 2 and graph["nodes"][0]["issue_count"] == 0


