"""注册表校验：合法项目通过；每条规则都有一个"坏注册表必须被拒"的用例。"""

import copy

import pytest

from dsflow.core.lifecycle import build_graph
from dsflow.core.validate import parse_registry, validate_registry


def codes(reg, root):
    return {i.code for i in validate_registry(reg, root)}


def test_valid_project_passes(mini_project):
    root, reg = mini_project
    assert validate_registry(reg, root) == []


def _mut(fn):
    def apply(reg):
        reg = copy.deepcopy(reg)
        fn(reg)
        return reg
    return apply


BROKEN = {
    "duplicate_id": _mut(lambda r: r["steps"][1].update(id="1.1")),
    "order_gap": _mut(lambda r: r["steps"][2].update(order=5)),
    "id_format": _mut(lambda r: r["steps"][1].update(id="1-2")),
    "id_stage_mismatch": _mut(lambda r: r["steps"][2].update(id="3.1", dir="steps/02_EDA/3.1_探索")),
    "unknown_stage": _mut(lambda r: r["steps"][2].update(stage=9, id="9.1")),
    "dir_outside_stage": _mut(lambda r: r["steps"][1].update(dir="steps/02_EDA/1.2_清洗")),
    "dir_name": _mut(lambda r: r["steps"][1].update(dir="steps/01_数据预处理/清洗")),
    "acceptance_report": _mut(lambda r: r["steps"][0].update(acceptance_report="elsewhere/report.md")),
    "missing_file": _mut(lambda r: r["steps"][1].update(status="done")),
    "notebook": _mut(lambda r: r["steps"][0].update(execution_notebooks=["missing/notebook.ipynb"])),
    "no_notebook": _mut(lambda r: r["steps"][0].update(execution_notebooks=[])),
    "current_revision": _mut(lambda r: r["steps"][0].update(current_revision="r09")),
    "duplicate_revision": _mut(lambda r: r["steps"][0]["revisions"][1].update(id="r01")),
    "revision_dir": _mut(lambda r: r["steps"][0]["revisions"][1].update(dir="steps/01_数据预处理/1.1_盘点/revisions/r02_不存在")),
    "no_dependencies": _mut(lambda r: r.pop("dependencies")),
    "dependency_ref": _mut(lambda r: r["dependencies"][0].update(to="1.999")),
    "back_edge_ref": _mut(lambda r: r["back_edges"].append({"from": "2.1", "to": "0.9"})),
    "revision_loop_ref": _mut(lambda r: r["revision_loops"][0].update(to_revision="r07")),
    "group_ref": _mut(lambda r: r["steps"][1].update(group="g1")),
    "group_stage": _mut(lambda r: (r["groups"].update(g1={"name": "组"}), r["steps"][1].update(group="g1"), r["steps"][2].update(group="g1"))),
    "stage_numbering": _mut(lambda r: r["steps"][1].update(id="1.3", dir="steps/01_数据预处理/1.3_清洗")),
}


@pytest.mark.parametrize("code", sorted(BROKEN))
def test_broken_registry_rejected(mini_project, code):
    root, reg = mini_project
    assert code in codes(BROKEN[code](reg), root)


def test_report_heading_must_contain_id(mini_project):
    root, reg = mini_project
    (root / reg["steps"][0]["dir"] / "report.md").write_text("# 盘点报告\n", encoding="utf-8")
    assert "report_heading" in codes(reg, root)


def test_in_progress_requires_plan(mini_project):
    root, reg = mini_project
    reg = copy.deepcopy(reg)
    reg["steps"][1]["status"] = "in_progress"
    assert "missing_file" in codes(reg, root)


def test_schema_error_is_reported_not_raised(mini_project):
    root, reg = mini_project
    reg = copy.deepcopy(reg)
    del reg["steps"][0]["title"]
    reg["steps"][1]["status"] = "unknown_status"
    issues = validate_registry(reg, root)
    assert issues and all(i.code == "schema" for i in issues)


def test_no_implicit_edges_from_numbering(mini_project):
    root, reg = mini_project
    reg = copy.deepcopy(reg)
    reg["dependencies"] = []
    reg["revision_loops"] = []
    model, _ = parse_registry(reg)
    assert build_graph(model, root)["edges"] == []


def test_graph_nodes_and_edges(mini_project):
    root, reg = mini_project
    model, _ = parse_registry(reg)
    graph = build_graph(model, root)
    assert [n["id"] for n in graph["nodes"]] == ["1.1", "1.2", "2.1"]
    node = graph["nodes"][0]
    assert node["status_label"] == "已完成"
    assert node["report_available"] and node["report_path"].endswith("acceptance/report.md")
    assert [(e["from"], e["to"], e["type"]) for e in graph["edges"]] == [
        ("1.1", "1.2", "dependency"), ("1.2", "2.1", "dependency"), ("1.1", "1.1", "revision_loop"),
    ]


def test_pending_approval_needs_no_files(mini_project):
    root, reg = mini_project
    reg = copy.deepcopy(reg)
    reg["steps"][1]["status"] = "pending_approval"
    assert "missing_file" not in codes(reg, root)
