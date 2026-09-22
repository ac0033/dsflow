"""数据层的存量账：原存量 / 增减量 / 后存量，以及产物的口径（只算有用的最终文件）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dsflow.core.project import Project
from dsflow.data.cache import DataCache
from dsflow.data.datasets import DatasetStore
from dsflow.data.engine import DataError
from dsflow.data.steptables import NO_NOTE
from dsflow.data.stock import step_stock

from .conftest import S1, STEP_11, base_registry, write_registry


@pytest.fixture
def chain_project(tmp_path: Path) -> Project:
    """1.1 核对 orders_raw；1.2 产出 orders_clean 并替代 orders_raw；2.1 产出 panel。"""
    root = tmp_path / "proj"
    reg = base_registry()
    reg["steps"][1]["status"] = "done"
    for sid, d in (("1.1", STEP_11), ("1.2", f"{S1}/1.2_清洗"), ("2.1", "steps/02_EDA/2.1_探索")):
        (root / d).mkdir(parents=True, exist_ok=True)
        (root / d / "plan.md").write_text(f"# {sid}\n", encoding="utf-8")
        (root / d / "report.md").write_text(f"# {sid} 报告\n", encoding="utf-8")
        (root / d / f"nb_{sid}.ipynb").write_text(json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}), encoding="utf-8")
    write_registry(root, reg)
    data = root / "data"
    data.mkdir()
    (data / "raw.csv").write_text("SKU,数量\nA,5\nB,1\n", encoding="utf-8")
    (data / "clean.csv").write_text("SKU,数量,是否退货\nA,5,0\n", encoding="utf-8")
    (data / "panel.csv").write_text("SKU,月份,数量\nA,2026-01,5\n", encoding="utf-8")
    project = Project(root, readonly=False)
    store = DatasetStore(project)
    store.register("data/raw.csv", "orders_raw", "raw", description="一行 = 一个原始订单行")
    store.link("orders_raw", "1.1", "核对")
    store.register("data/clean.csv", "orders_clean", "processed", parents=["orders_raw"], produced_by="1.2",
                   replaces=["orders_raw"], description="一行 = 一个清洗后的订单行")
    store.register("data/panel.csv", "panel", "features", parents=["orders_clean"], produced_by="2.1",
                   description="一行 = 一个 SKU 的一个月")
    return project


def names(items: list[dict]) -> list[str]:
    return sorted(t["name"] for t in items)


def test_stock_walks_before_delta_after(chain_project):
    reg, _ = chain_project.load()
    s11 = step_stock(chain_project, reg, "1.1")
    assert names(s11["before"]) == ["orders_raw"] and s11["changes_data"] is False
    assert [t["role"] for t in s11["delta"]["checked"]] == ["核对"]
    assert names(s11["after"]) == ["orders_raw"]

    s12 = step_stock(chain_project, reg, "1.2")
    assert names(s12["before"]) == ["orders_raw"]
    assert names(s12["delta"]["added"]) == ["orders_clean"]
    assert [t["retired_by"] for t in s12["delta"]["retired"]] == ["orders_clean"]
    assert names(s12["after"]) == ["orders_clean"], "被替代的 orders_raw 退出后存量"
    assert s12["changes_data"] is True

    s21 = step_stock(chain_project, reg, "2.1")
    assert names(s21["before"]) == ["orders_clean"]
    assert names(s21["after"]) == ["orders_clean", "panel"]


def test_new_version_of_a_table_in_stock_is_an_update(chain_project):
    (chain_project.root / "data" / "clean.csv").write_text("SKU,数量,是否退货,金额未知\nA,5,0,0\n", encoding="utf-8")
    store = DatasetStore(chain_project)
    store.register("data/clean.csv", "orders_clean", "processed", parents=["orders_raw"], produced_by="2.1")
    reg, _ = chain_project.load()
    s21 = step_stock(chain_project, reg, "2.1")
    up = s21["delta"]["updated"]
    assert names(up) == ["orders_clean"] and up[0]["previous_version"] and up[0]["previous_version"] != up[0]["version"]
    assert names(s21["delta"]["added"]) == ["panel"]
    assert names(s21["after"]) == ["orders_clean", "panel"]


def test_delta_tells_which_tables_became_which(chain_project):
    """增减量要能直接画出「哪几张表变成了哪张表」：上游表的规模、旧版本的规模、接手的表都带在里面。"""
    # 行列数要数得出来，两张表都得先转成 Parquet（平台上是用户打开一次就转好）
    for rel in ("data/raw.csv", "data/clean.csv"):
        DataCache(chain_project).prepare(rel)
    reg, _ = chain_project.load()
    s12 = step_stock(chain_project, reg, "1.2")
    clean = s12["delta"]["added"][0]
    assert [x["name"] for x in clean["sources"]] == ["orders_raw"]
    assert clean["sources"][0]["rows"] == 2 and clean["sources"][0]["columns"] == 2, "上游表的行列数要给出来，前端才画得出变化"
    assert clean["rows"] == 1 and clean["columns"] == 3
    assert clean["diff"]["added"] == ["是否退货"] and clean["diff"]["removed"] == []

    gone = s12["delta"]["retired"][0]
    assert gone["name"] == "orders_raw" and gone["retired_by"] == "orders_clean"
    assert gone["retired_by_rows"] == 1 and gone["retired_by_columns"] == 3, "退出的表要说明谁接手、接手的表多大"


def test_update_carries_the_old_shape(chain_project):
    """同一张表重算：旧版本的行列数也要带上，才能说清这一轮多了几行几列。"""
    DataCache(chain_project).prepare("data/clean.csv")   # 旧版本先转好，才数得出它原来几行
    (chain_project.root / "data" / "clean.csv").write_text("SKU,数量,是否退货,金额未知\nA,5,0,0\nB,1,0,0\n", encoding="utf-8")
    DataCache(chain_project).prepare("data/clean.csv")
    DatasetStore(chain_project).register("data/clean.csv", "orders_clean", "processed", parents=["orders_raw"], produced_by="2.1")
    reg, _ = chain_project.load()
    up = step_stock(chain_project, reg, "2.1")["delta"]["updated"][0]
    assert up["previous_rows"] == 1 and up["previous_columns"] == 3
    assert up["rows"] == 2 and up["columns"] == 4
    assert up["diff"]["added"] == ["金额未知"]


def test_replace_command_validates_names(chain_project):
    store = DatasetStore(chain_project)
    with pytest.raises(DataError):
        store.set_replaces("panel", ["nowhere"])
    with pytest.raises(DataError):
        store.set_replaces("panel", ["panel"])
    store.set_replaces("panel", ["orders_clean"])
    assert store.chain()[-1]["replaces"] == ["orders_clean"]
    reg, _ = chain_project.load()
    assert names(step_stock(chain_project, reg, "2.1")["after"]) == ["panel"]


def test_middles_list_the_scratch_data_files_but_not_the_reports(chain_project):
    """中间产物：本轮留下的数据文件（核对清单这类）单独列出来，能打开看；报告、说明卡不在这里。"""
    root = chain_project.root
    rev_dir = f"{S1}/1.2_清洗"
    (root / rev_dir / "outputs").mkdir(exist_ok=True)
    (root / rev_dir / "outputs" / "check_only.csv").write_text("a\n1\n", encoding="utf-8")
    (root / rev_dir / "outputs" / "决策清单.json").write_text("{}", encoding="utf-8")
    reg, _ = chain_project.load()
    s12 = step_stock(chain_project, reg, "1.2")
    middles = {t["name"]: t for t in s12["middles"]}
    assert "check_only.csv" in middles and middles["check_only.csv"]["role"] == "中间产物"
    assert "决策清单.json" not in middles, "json 不是数据表，不进数据选项卡"
    assert "report.md" not in middles
    assert all(t["name"] != "check_only.csv" for t in s12["delta"]["added"]), "中间产物不算存量账里的产物"


def test_reports_and_declared_artifacts_are_products_but_scratch_files_are_not(chain_project):
    root = chain_project.root
    rev_dir = f"{S1}/1.2_清洗"
    (root / rev_dir / "outputs").mkdir()
    (root / rev_dir / "outputs" / "check_only.csv").write_text("a\n1\n", encoding="utf-8")
    (root / rev_dir / "outputs" / "ledger.csv").write_text("处理,行数\n原始,2\n", encoding="utf-8")
    (root / rev_dir / "step_card.yaml").write_text(
        "step: '1.2'\nheadline: 清洗完成\ncan_continue: true\nartifacts:\n  - {path: outputs/ledger.csv, purpose: 行数台账, kind: table}\n",
        encoding="utf-8")
    reg, _ = chain_project.load()
    s12 = step_stock(chain_project, reg, "1.2")
    added = {t["name"]: t for t in s12["delta"]["added"]}
    assert "ledger.csv" in added and added["ledger.csv"]["note"] == "行数台账" and added["ledger.csv"].get("declared")
    assert "check_only.csv" not in added, "没登记、没声明用途的中间文件不算产物"
    assert [o["kind_label"] for o in s12["delta"]["others"]] == ["用户报告"]
    middle = {t["name"]: t for t in s12["middles"]}
    assert middle["check_only.csv"]["note"] == NO_NOTE and middle["check_only.csv"]["note_missing"]
    assert not added["ledger.csv"]["note_missing"], "声明了用途的产物，用途就是它的介绍"


def test_revision_without_summary_is_flagged(mini_project):
    from dsflow.progress.alerts import compute_alerts

    root, reg_raw = mini_project
    project = Project(root, readonly=False)
    reg, issues = project.load()
    assert "revision_no_summary" not in [a["code"] for a in compute_alerts(project, reg, issues, [])]
    reg_raw["steps"][0]["revisions"][1]["summary"] = ""
    write_registry(root, reg_raw)
    reg, issues = project.load()
    flagged = [a for a in compute_alerts(project, reg, issues, []) if a["code"] == "revision_no_summary"]
    assert len(flagged) == 1 and "r02" in flagged[0]["message"] and flagged[0]["step"] == "1.1"
