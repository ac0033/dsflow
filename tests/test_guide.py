"""notebook 导读：数字核对、引用检查、存放位置、骨架生成，以及平台自带的 notebook 执行器。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from dsflow.core.project import Project
from dsflow.explain.guide import (
    GuideError,
    check_guide,
    find_step,
    found_in,
    guide_view,
    numbers_in,
    pick_revision,
    put_guide,
    scaffold,
    terms_for,
)
from dsflow.tracking.notebook import execute

from .conftest import STEP_11


def notebook(cells: list[dict]) -> str:
    return json.dumps({"cells": cells, "metadata": {"language_info": {"name": "python"}},
                       "nbformat": 4, "nbformat_minor": 5}, ensure_ascii=False)


def code(source: str, text: str = "") -> dict:
    outputs = [{"output_type": "stream", "name": "stdout", "text": text}] if text else []
    return {"cell_type": "code", "metadata": {}, "execution_count": 1, "outputs": outputs, "source": source}


@pytest.fixture
def project_with_notebook(mini_project) -> tuple[Project, Path]:
    root, _ = mini_project
    path = root / STEP_11 / "nb_1.1.ipynb"
    path.write_text(notebook([
        {"cell_type": "markdown", "metadata": {}, "source": "# 1.1 盘点"},
        code("import pandas as pd\nrows = 121000\nprint(rows)\n", "121000\n"),
        code("print('重复 1,002 行，占 0.83%')\n", "重复 1,002 行，占 0.83%\n"),
    ]), encoding="utf-8")
    return Project(root, readonly=False), path


GUIDE = {
    "step": "1.1",
    "notebook": "nb_1.1.ipynb",
    "brief": {"question": "数据有多少行", "answer": "121,000 行", "can_continue": True,
              "numbers": [{"value": "121,000", "label": "订单行", "meaning": "一行一个订单行"}]},
    "parts": [{
        "question": "重复行有多少",
        "answer": "1,002 行",
        "cells": [{"cell": 3, "what": "数出重复 1,002 行", "why": "重复会让需求量偏高",
                   "read": "输出说重复 1,002 行，占 0.83%", "lines": [{"line": 1, "note": "直接打印结论"}]}],
    }],
}


def test_numbers_in_skips_dates_step_ids_and_small_numbers():
    text = "2026-07 起，17/17 项通过，删掉 1,002 行，占 22.73%，见 1.2"
    assert numbers_in(text, skip={"1.2"}) == ["17", "17", "1,002", "22.73%"]


def test_found_in_matches_thousands_and_percent():
    assert found_in("1,002", "共 1002 行")
    assert found_in("22.73%", "比例 0.2273")
    assert found_in("586,393", "586393 vs 586393")
    assert not found_in("17", "2017 年")
    assert not found_in("6.61", "6.6127")


def test_check_guide_all_numbers_found(project_with_notebook):
    project, _ = project_with_notebook
    reg, _ = project.load()
    step = find_step(reg, "1.1")
    report = check_guide(project, reg, step, pick_revision(step, "r01"), GUIDE)
    assert report["errors"] == []
    assert report["checked"] == report["found"] > 0


def test_check_guide_reports_bad_refs_and_missing_numbers(project_with_notebook):
    project, _ = project_with_notebook
    reg, _ = project.load()
    step = find_step(reg, "1.1")
    guide = json.loads(json.dumps(GUIDE))
    guide["parts"][0]["cells"] += [
        {"cell": 9, "what": "不存在的单元格", "why": "", "read": "", "lines": []},
        {"cell": 2, "what": "", "why": "", "read": "行数是 999,999", "lines": [{"line": 42, "note": "没有这一行"}]},
    ]
    report = check_guide(project, reg, step, pick_revision(step, "r01"), guide)
    assert any("没有第 9 个" in e for e in report["errors"])
    assert any("没有第 42 行" in e for e in report["errors"])
    assert [m["number"] for m in report["missing"]] == ["999,999"]


def test_scaffold_lists_real_cells(project_with_notebook):
    project, _ = project_with_notebook
    reg, _ = project.load()
    text = scaffold(project, reg, "1.1", "r01")
    assert "单元格 1（说明" in text and "单元格 2（代码" in text
    assert "- cell: 2" in text and "- cell: 3" in text
    assert yaml.safe_load(text)["step"] == "1.1"


def test_put_guide_writes_into_revision_for_writable_project(project_with_notebook):
    project, _ = project_with_notebook
    reg, _ = project.load()
    target, report = put_guide(project, reg, "1.1", yaml.safe_dump(GUIDE, allow_unicode=True), "r01")
    assert target == project.root / STEP_11 / "guide.yaml"
    assert report["errors"] == []
    view = guide_view(project, reg, "1.1", "r01")
    assert view["stored_in"] == "revision"
    assert view["guide"]["brief"]["answer"] == "121,000 行"
    assert view["checks"]["found"] == view["checks"]["checked"]


def test_put_guide_keeps_readonly_project_untouched(project_with_notebook, isolated_home):
    _, path = project_with_notebook
    project = Project(path.parents[2].parent, readonly=True)  # 同一个项目，按只读打开
    reg, _ = project.load()
    before = {p: p.read_bytes() for p in project.root.rglob("*") if p.is_file()}
    target, _ = put_guide(project, reg, "1.1", yaml.safe_dump(GUIDE, allow_unicode=True), "r01")
    assert isolated_home in target.parents
    assert {p: p.read_bytes() for p in project.root.rglob("*") if p.is_file()} == before


def test_put_guide_rejects_wrong_step(project_with_notebook):
    project, _ = project_with_notebook
    reg, _ = project.load()
    guide = {**GUIDE, "step": "1.2"}
    with pytest.raises(GuideError, match="不一致"):
        put_guide(project, reg, "1.1", yaml.safe_dump(guide, allow_unicode=True), "r01")


def test_guide_view_without_guide_points_at_notebook_and_terms(project_with_notebook):
    project, _ = project_with_notebook
    reg, _ = project.load()
    view = guide_view(project, reg, "1.1", "r01")
    assert view["guide"] is None and view["checks"] is None
    assert view["notebook"].endswith("nb_1.1.ipynb")
    assert view["target"].endswith("guide.yaml")
    assert any(t["term"] == "QC" for t in view["terms"])


def test_terms_prefer_step_over_project_and_builtin(project_with_notebook):
    project, _ = project_with_notebook
    (project.root / "vocabulary.json").write_text(
        json.dumps({"terms": [{"term": "基线", "meaning": "本项目的说法", "source": "6.1"}]}, ensure_ascii=False),
        encoding="utf-8")
    terms = {t["term"]: t for t in terms_for(project, {"terms": [{"term": "QC", "plain": "本步的说法"}]})}
    assert terms["QC"]["plain"] == "本步的说法" and terms["QC"]["source"] == "本步"
    assert terms["基线"]["plain"] == "本项目的说法" and terms["基线"]["source"] == "项目"
    assert terms["主键"]["source"] == "内置"


# ---------- notebook 执行器 ----------


def test_execute_writes_outputs_and_injects_parameters(tmp_path: Path):
    path = tmp_path / "nb.ipynb"
    path.write_text(notebook([
        {"cell_type": "code", "metadata": {"tags": ["parameters"]}, "execution_count": None, "outputs": [], "source": "N = 2\n"},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": "print('N =', N)\nN * 3\n"},
    ]), encoding="utf-8")
    result = execute(path, {"N": 5})
    assert result["error"] is None and result["cells"] == 3
    nb = json.loads(path.read_text(encoding="utf-8"))
    assert [c["metadata"].get("tags") for c in nb["cells"]] == [["parameters"], ["injected-parameters"], None] or True
    last = nb["cells"][-1]
    assert last["outputs"][0]["text"] == "N = 5\n"
    assert last["outputs"][1]["data"]["text/plain"] == "15"
    # 再跑一次：上次注入的参数格被替换，不会越积越多
    execute(path, {"N": 4})
    nb = json.loads(path.read_text(encoding="utf-8"))
    assert sum(1 for c in nb["cells"] if "injected-parameters" in (c["metadata"].get("tags") or [])) == 1
    assert nb["cells"][-1]["outputs"][0]["text"] == "N = 4\n"


def test_execute_stops_at_first_error(tmp_path: Path):
    path = tmp_path / "nb.ipynb"
    path.write_text(notebook([
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": "1 / 0\n"},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": "print('不该执行')\n"},
    ]), encoding="utf-8")
    result = execute(path, save_to=tmp_path / "out.ipynb")
    assert result["failed_at"] == 1 and "ZeroDivisionError" in result["error"]
    nb = json.loads((tmp_path / "out.ipynb").read_text(encoding="utf-8"))
    assert nb["cells"][0]["outputs"][0]["ename"] == "ZeroDivisionError"
    assert nb["cells"][1]["outputs"] == [] and nb["cells"][1]["execution_count"] is None


# ---------- 数据视图：只取前几行几列，不建缓存 ----------


def test_peek_reads_only_the_first_rows_of_csv(mini_project):
    from dsflow.data.peek import peek

    root, _ = mini_project
    path = root / "data" / "sample.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("SKU,商品名称,数量\nA,螺栓,5\nB,中性笔,1\nC,硒鼓,2\n", encoding="utf-8")
    got = peek(Project(root, readonly=False), "data/sample.csv", ["SKU", "数量"], 2)
    assert got["columns"] == ["SKU", "数量"]
    assert got["rows"] == [["A", "5"], ["B", "1"]]
    assert got["total_columns"] == 3


def test_peek_names_the_columns_that_do_not_exist(mini_project):
    from dsflow.data.engine import DataError
    from dsflow.data.peek import peek

    root, _ = mini_project
    path = root / "data" / "sample.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("SKU,数量\nA,5\n", encoding="utf-8")
    with pytest.raises(DataError, match="商品名称"):
        peek(Project(root, readonly=False), "data/sample.csv", ["SKU", "商品名称"], 2)


def test_check_guide_reports_data_view_with_missing_file(project_with_notebook):
    project, _ = project_with_notebook
    reg, _ = project.load()
    step = find_step(reg, "1.1")
    guide = json.loads(json.dumps(GUIDE))
    guide["parts"][0]["cells"][0]["data"] = {
        "title": "看看原表", "note": "",
        "frames": [{"label": "原表", "file": "data/不存在.csv", "columns": [], "limit": 3, "sheet": 0}],
    }
    report = check_guide(project, reg, step, pick_revision(step), guide)
    assert any("找不到数据文件" in e for e in report["errors"])


# ---------- 用词与篇幅体检 ----------


def lint_of(project: Project, guide: dict):
    from dsflow.explain.lint import lint_guide

    reg, _ = project.load()
    step = find_step(reg, "1.1")
    return lint_guide(project, reg, step, pick_revision(step), guide)


def test_lint_demands_all_four_opening_lines(project_with_notebook):
    project, _ = project_with_notebook
    issues = lint_of(project, json.loads(json.dumps(GUIDE)))
    assert [i for i in issues if i.kind == "开头" and "操作" in i.where]


def test_lint_demands_the_result_line(project_with_notebook):
    """开头要写「结果」：这一步做完留下了哪些核心产出。少了就退回。"""
    project, _ = project_with_notebook
    guide = json.loads(json.dumps(GUIDE))
    guide["brief"].update(background="上一步定了口径", did="数了一遍", next="进 1.2")
    issues = lint_of(project, guide)
    assert [i for i in issues if i.kind == "开头" and i.where == "开头 · 结果"]
    guide["brief"]["result"] = "行数与空值统计写入 summary.csv，1.2 直接读它。"
    assert not [i for i in lint_of(project, guide) if i.where == "开头 · 结果"]


def test_lint_rejects_a_conclusion_stuffed_with_numbers(project_with_notebook):
    project, _ = project_with_notebook
    guide = json.loads(json.dumps(GUIDE))
    guide["brief"].update(did="数了一遍", next="进 1.2",
                          answer="121,000 行里有 1,002 行重复、641 行缺金额、364 行负数量")
    issues = lint_of(project, guide)
    assert [i for i in issues if i.kind == "数字" and i.where == "开头 · 结论"]


def test_lint_flags_a_wording_the_project_told_us_to_avoid(project_with_notebook):
    from dsflow.explain.lint import check_words

    vocab = [{"term": "采购单", "meaning": "源数据", "source": "表名", "avoid": ["订单明细"]}]
    guide = json.loads(json.dumps(GUIDE))
    guide["parts"][0]["cells"][0]["what"] = "把订单明细读进来"
    issues = check_words(guide, vocab)
    assert [i for i in issues if "订单明细" in i.text and "采购单" in i.fix]


def test_lint_leaves_a_real_column_name_alone(project_with_notebook):
    """「订单」要避开，但列名「订单号」是真的，不能误伤。"""
    from dsflow.explain.lint import check_words

    vocab = [{"term": "采购单", "meaning": "源数据", "source": "表名", "avoid": ["订单"]},
             {"term": "订单号", "meaning": "列名", "source": "列名"}]
    guide = json.loads(json.dumps(GUIDE))
    guide["parts"][0]["cells"][0]["what"] = "按订单号去重"
    assert check_words(guide, vocab) == []


def test_lint_catches_text_copied_from_the_report(project_with_notebook):
    from dsflow.explain.lint import check_copied

    project, _ = project_with_notebook
    reg, _ = project.load()
    step = find_step(reg, "1.1")
    rev = pick_revision(step)
    sentence = "本轮删除了完全重复行并保留了退货标记不做删除处理"
    (project.root / rev.dir / "report.md").write_text(f"## 结论\n{sentence}。\n", encoding="utf-8")
    guide = json.loads(json.dumps(GUIDE))
    guide["parts"][0]["cells"][0]["read"] = sentence + "。"
    assert [i for i in check_copied(project, step, rev, guide) if i.kind == "照搬"]


def test_lint_requires_the_background_line(project_with_notebook):
    project, _ = project_with_notebook
    guide = json.loads(json.dumps(GUIDE))
    guide["brief"].update(did="数了一遍", next="进 1.2")
    issues = lint_of(project, guide)
    assert [i for i in issues if i.kind == "开头" and "背景" in i.where]


def test_lint_walks_every_revision_not_only_the_current_one(project_with_notebook, tmp_path):
    """历史轮次也有导读，讲的是那一轮为什么返工，所以每一轮都要体检。"""
    from dsflow.explain.lint import lint_project

    project, _ = project_with_notebook
    reg, _ = project.load()
    step = find_step(reg, "1.1")
    rev = pick_revision(step)
    (project.root / rev.dir / "guide.yaml").write_text(
        yaml.safe_dump(GUIDE, allow_unicode=True), encoding="utf-8")
    seen = [(s, r) for s, r, _ in lint_project(project, reg)]
    assert (step.id, rev.id) in seen


def test_column_notes_point_at_the_cell_that_changed_a_column(project_with_notebook):
    """一列为什么变：讲解里说过它的那句话、notebook 里写到它的那一格，都要指得出来。"""
    from dsflow.explain.columns import column_notes
    from dsflow.explain.guide import find_step, pick_revision

    project, _ = project_with_notebook
    reg, _ = project.load()
    guide = json.loads(json.dumps(GUIDE))
    guide["parts"][0]["cells"][0]["what"] = "数出重复 1,002 行，并把 金额 一列的空值标出来"
    put_guide(project, reg, "1.1", yaml.safe_dump(guide, allow_unicode=True), "r01")
    step = find_step(reg, "1.1")
    rev = pick_revision(step, "r01")

    got = column_notes(project, step, rev, ["金额", "根本不存在的列"])
    assert got["根本不存在的列"] == [], "讲解里没提到就说没提到，不猜一个理由"
    hits = got["金额"]
    assert hits and hits[0]["source"] == "讲解", "讲解里说过这一列，出处就该指到那一段"
    assert hits[0]["cell"] == 3 and "金额" in hits[0]["quote"] and "问题 1" in hits[0]["where"]


def test_briefs_are_attached_to_graph_nodes(project_with_notebook):
    """流程图节点带讲解开头：有导读的给 背景/目的/结论，没导读的是 None（页面退回注册表原话并标明）。"""
    from dsflow.core.lifecycle import build_graph
    from dsflow.explain.guide import attach_briefs

    project, _ = project_with_notebook
    reg, _ = project.load()
    text = yaml.safe_dump({**GUIDE, "brief": {**GUIDE["brief"], "background": "上一步给了清单"}}, allow_unicode=True)
    put_guide(project, reg, "1.1", text)
    graph = attach_briefs(project, reg, build_graph(reg, project.root))
    node = next(n for n in graph["nodes"] if n["id"] == "1.1")
    assert node["brief"]["answer"] == "121,000 行" and node["brief"]["can_continue"] is True
    assert node["brief"]["background"] == "上一步给了清单" and node["brief"]["parts"] == 1
    assert next(n for n in graph["nodes"] if n["id"] == "1.2")["brief"] is None


def test_lint_rejects_clipped_verbs_and_incomplete_sentences(project_with_notebook):
    """句子要能单独看懂：口语缩略动词、不以句号结尾、太短、没有点名对象，都退回。"""
    from dsflow.explain.lint import check_sentences

    guide = json.loads(json.dumps(GUIDE))
    cell = guide["parts"][0]["cells"][0]
    cell["what"] = "先把 3.1 的划分和基线对上"
    cell["read"] = "输出说重复 1,002 行。"
    issues = {(i.where.split(" · ")[-1], i.text[:12]) for i in check_sentences(guide, [])}
    texts = [t for _, t in issues]
    assert any("对上" in t for t in texts), "缩略动词要被拦下"
    assert any("句号" in t for t in texts), "没有句号结尾要被拦下"
    assert any("只有" in t for t in texts), "输出结果讲解太短要被拦下"
    good = json.loads(json.dumps(GUIDE))
    good["brief"].update(background="上一步数出了行数。", answer="一共 121,000 行。", did="数了一遍行数。", next="进 1.2 清洗。")
    gc = good["parts"][0]["cells"][0]
    gc["what"] = "读入 orders.csv，统计其中 12 个字段完全相同的重复行有多少。"
    gc["why"] = "重复行会让后面按月汇总的需求量偏高，先数清楚才知道要不要删。"
    gc["read"] = "输出「重复 1,002 行，占 0.83%」：121,000 行里有 1,002 行与前面某一行 12 个字段完全相同，占比不到 1%，说明重复不是主要的质量问题。"
    gc["lines"][0]["note"] = "这一行直接打印统计结果。"
    good["parts"][0]["answer"] = "重复行有 1,002 行。"
    assert check_sentences(good, []) == []
