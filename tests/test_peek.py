"""讲解旁的数据视图（peek）：分号、制表符分隔的 CSV 也要能按列取。"""

from __future__ import annotations

from dsflow.core.project import Project
from dsflow.data.peek import peek


def test_peek_detects_semicolon_and_tab_delimiters(mini_project):
    root, _ = mini_project
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "semi.csv").write_text('"fixed acidity";"alcohol";"quality"\n7.4;9.4;5\n7.8;9.8;5\n', encoding="utf-8")
    (data / "tab.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
    (data / "comma.csv").write_text("a,b;c\n1,2;3\n", encoding="utf-8")
    project = Project(root, readonly=False)
    got = peek(project, "data/semi.csv", ["alcohol", "quality"], 5)
    assert got["columns"] == ["alcohol", "quality"] and got["rows"] == [["9.4", "5"], ["9.8", "5"]] and got["total_columns"] == 3
    assert peek(project, "data/tab.tsv", [], 5)["columns"] == ["a", "b"]
    assert peek(project, "data/comma.csv", [], 5)["columns"] == ["a", "b;c"], "逗号更多时仍按逗号切"
