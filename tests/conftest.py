import json
from pathlib import Path

import pytest

S1 = "steps/01_数据预处理"
STEP_11 = f"{S1}/1.1_盘点"
REV_11 = f"{STEP_11}/revisions/r02_2026-09-15_修正"


def base_registry() -> dict:
    return {
        "title": "测试项目",
        "stages": [
            {"id": 1, "name": "① 数据预处理", "dir": S1, "color": "#3b82f6"},
            {"id": 2, "name": "② EDA", "dir": "steps/02_EDA", "color": "#10b981"},
        ],
        "steps": [
            {
                "id": "1.1", "stage": 1, "order": 1, "title": "盘点", "dir": STEP_11, "status": "done",
                "op": "确认字段", "finding": "字段含义清楚", "decision": "进入 1.2",
                "current_revision": "r02",
                "revisions": [
                    {"id": "r01", "status": "partial", "dir": STEP_11},
                    {"id": "r02", "status": "done", "dir": REV_11, "summary": "按验收意见补齐字段含义后重做"},
                ],
                "acceptance_report": f"{REV_11}/acceptance/report.md",
            },
            {"id": "1.2", "stage": 1, "order": 2, "title": "清洗", "dir": f"{S1}/1.2_清洗", "status": "pending"},
            {"id": "2.1", "stage": 2, "order": 3, "title": "探索", "dir": "steps/02_EDA/2.1_探索", "status": "pending"},
        ],
        "dependencies": [
            {"from": "1.1", "to": "1.2", "label": "字段清单"},
            {"from": "1.2", "to": "2.1", "label": "清洗后数据"},
        ],
        "back_edges": [],
        "revision_loops": [{"step": "1.1", "from_revision": "r01", "to_revision": "r02", "label": "验收退回"}],
        "groups": {},
        "notes": "测试用",
    }


def write_registry(root: Path, reg: dict) -> None:
    path = root / "lifecycle" / "steps.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def mini_project(tmp_path: Path) -> tuple[Path, dict]:
    """一个能通过全部校验的小项目：1.1 已完成且有两轮，1.2 / 2.1 未开始。"""
    root = tmp_path / "proj"
    reg = base_registry()
    _touch(root / STEP_11 / "plan.md", "# 1.1 计划\n")
    _touch(root / STEP_11 / "report.md", "# 1.1 盘点报告\n\n正文\n")
    _touch(root / STEP_11 / "nb_1.1.ipynb", "{}")
    _touch(root / REV_11 / "plan.md", "# 1.1 r02 计划\n")
    _touch(root / REV_11 / "acceptance" / "report.md", "# 1.1 r02 主验收\n")
    _touch(root / REV_11 / "guide.yaml", 'step: "1.1"\nbrief:\n  question: 字段含义是否清楚\n  answer: 字段含义已经逐个确认清楚。\n')
    write_registry(root, reg)
    return root, reg


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "dsflow_home"
    monkeypatch.setenv("DSFLOW_HOME", str(home))
    return home
