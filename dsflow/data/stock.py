"""数据层的存量账：每一步执行前有哪些有用的最终文件（原存量）、这一步增减了什么（增减量）、执行完剩哪些（后存量）。

产物的口径：**有实际用处的最终文件**——后续步骤要用的表、给业务看的报告、登记过的模型。中间结果、
只为核对用的清单、验证后的一次性结果都不算，所以这里只认登记过的数据集（`dsflow data add` / SDK `log_output`）、
说明卡里声明了用途的产物、本轮的用户报告与主验收报告。

存量按步骤的执行顺序推演：一开始的存量是没有产出步骤的数据集（原始数据、从旧项目带来的表）；
每一步把它产出的数据集加进来（已在存量里的算「更新」，换了新版本），
再把它声明 `replaces` 的旧表移出去（「退出」：被新表替代，以后不该再用）。
"""

from __future__ import annotations

import posixpath
from pathlib import Path

from ..core.project import Project
from ..core.schemas import Registry, Revision, Step
from ..core.steps import load_card, revision_files, revisions_of
from ..tracking.store import RunStore
from .cache import DataCache
from .datasets import STAGE_LABEL, DatasetStore
from .files import data_format
from .steptables import _columns_of, _entry, diff_columns, guide_frames, version_columns, version_shape

KIND_LABEL = {"report": "用户报告", "acceptance_report": "验收报告"}


def _pick_revision(step: Step, rev_id: str | None) -> Revision:
    revs = revisions_of(step)
    return next((r for r in revs if r.id == (rev_id or step.current_revision)), revs[-1])


def _ledger(datasets: list[dict], order: dict[str, int]) -> tuple[list[str], dict[str, list[dict]]]:
    """（一开始就在存量里的数据集, 步骤 → 它产出的版本）。同一步骤产出同一数据集多次只算最后一次。"""
    initial: list[str] = []
    by_step: dict[str, dict[str, dict]] = {}
    for d in datasets:
        versions = d["versions"]
        first = versions[0]
        if not first.get("produced_by") or first["produced_by"] not in order:
            initial.append(d["name"])
        for i, v in enumerate(versions):
            step = v.get("produced_by")
            if not step or step not in order:
                continue
            previous = next((p for p in reversed(versions[:i]) if p.get("produced_by") != step), None)
            by_step.setdefault(step, {})[d["name"]] = {**v, "description": d.get("description", ""),
                                                        "previous": previous, "used_by": d.get("used_by") or []}
    return initial, {s: list(items.values()) for s, items in by_step.items()}


def _sources(cache: DataCache, names: list[str], stock: dict[str, dict], latest: dict[str, dict]) -> list[dict]:
    """新增的表是从哪几张表来的：每张上游表的名字、规模。一张就是"由它做出来"，多张就是"合并"。"""
    out: list[dict] = []
    for name in names:
        v = stock.get(name) or latest.get(name)
        if v is None:
            out.append({"name": name, "path": None, "rows": None, "columns": None, "missing": True, "ready": False})
            continue
        shape = version_shape(cache, v)
        out.append({"name": name, "path": v["path"], "version": v.get("version"), "rows": shape["rows"],
                    "columns": shape["columns"], "missing": shape["missing"], "ready": shape["ready"]})
    return out


def _table(cache: DataCache, frames: dict, v: dict, role: str, **extra) -> dict:
    entry = _entry(cache, v["name"], v["path"], role, v.get("description", ""),
                   stage=v.get("stage"), stage_label=STAGE_LABEL.get(v.get("stage", ""), v.get("stage", "")),
                   version=v.get("version"), produced_by=v.get("produced_by"), parents=v.get("parents") or [],
                   replaces=v.get("replaces") or [], **extra)
    if entry.get("rows") is None:   # 指纹本过期时按登记的哈希再找一次那一版的缓存
        shape = version_shape(cache, v)
        if shape["rows"] is not None:
            entry.update(ready=True, rows=shape["rows"], columns=shape["columns"])
    entry["guide_refs"] = frames.get(posixpath.normpath(v["path"]), [])
    return entry


def step_stock(project: Project, reg: Registry, step_id: str, rev_id: str | None = None) -> dict:
    step = next((s for s in reg.steps if s.id == step_id), None)
    if step is None:
        raise KeyError(f"步骤 {step_id} 不存在")
    rev = _pick_revision(step, rev_id)
    order = {s.id: s.order for s in reg.steps}
    cache = DataCache(project)
    store = DatasetStore(project)
    datasets = store.list()
    latest = {d["name"]: {**d["versions"][-1], "description": d.get("description", "")} for d in datasets}
    initial, by_step = _ledger(datasets, order)
    frames = guide_frames(project, step, rev)

    # 从头推演到这一步之前：存量里每个名字对应「那时的版本」
    stock: dict[str, dict] = {n: datasets_first(datasets, n) for n in initial}
    for s in sorted(reg.steps, key=lambda x: x.order):
        if s.order >= step.order:
            break
        for v in by_step.get(s.id, []):
            stock[v["name"]] = v
        for v in by_step.get(s.id, []):
            for old in v.get("replaces") or []:
                stock.pop(old, None)
    before = [_table(cache, frames, v, "存量") for v in stock.values()]

    # 这一步的增减
    produced = by_step.get(step.id, [])
    added, updated, retired = [], [], []
    for v in produced:
        base_name, base_cols = None, None
        if v["name"] in stock:
            old = stock[v["name"]]
            old_shape = version_shape(cache, old, exact=True)
            entry = _table(cache, frames, v, "更新", previous_version=old.get("version"), previous_path=old.get("path"),
                           previous_rows=old_shape["rows"], previous_columns=old_shape["columns"],
                           diff_base=f"{v['name']} 旧版本 {old.get('version')}",
                           diff=diff_columns(version_columns(cache, old, exact=True), _columns_of(cache, v["path"])))
            updated.append(entry)
            continue
        base_path = None
        for name in v.get("parents") or []:
            source = stock.get(name) or latest.get(name)
            if source is None:
                continue
            cols = version_columns(cache, source)
            if base_path is None:
                base_name, base_path = name, source["path"]
            if cols is not None:
                base_name, base_path, base_cols = name, source["path"], cols
                break
        added.append(_table(cache, frames, v, "新增", diff_base=base_name, diff_base_path=base_path,
                            sources=_sources(cache, v.get("parents") or [], stock, latest),
                            diff=diff_columns(base_cols, _columns_of(cache, v["path"])) if base_name else None))
    after = dict(stock)
    for v in produced:
        after[v["name"]] = v
    for v in produced:
        for old in v.get("replaces") or []:
            if old in stock:
                new_shape = version_shape(cache, v)
                retired.append(_table(cache, frames, stock[old], "退出", retired_by=v["name"],
                                      retired_by_path=v["path"], retired_by_rows=new_shape["rows"],
                                      retired_by_columns=new_shape["columns"]))
                after.pop(old, None)

    # 只读没改的表：登记的用途 + 运行记录里的输入
    seen = {t["path"] for t in [*added, *updated, *retired]}
    checked: list[dict] = []
    roles = {d["name"]: u["role"] for d in datasets for u in (d.get("used_by") or []) if u.get("step") == step_id}
    for run in RunStore(project).list(step_id):
        for ref in run.get("inputs") or []:
            if ref.get("name") in latest:
                roles.setdefault(ref["name"], "读取")
    for name, role in sorted(roles.items()):
        v = stock.get(name) or latest.get(name)
        if v and v["path"] not in seen:
            seen.add(v["path"])
            checked.append(_table(cache, frames, v, role if role in ("核对", "读取") else "读取"))

    # 说明卡声明的产物（数据文件进「新增」）和本轮的报告归入其他产物
    others = _others(project, step, rev, cache, frames, added, seen)
    middles = _middles(project, step, rev, cache, frames, seen)

    return {
        "step": step.id,
        "revision": rev.id,
        "revision_dir": rev.dir,
        "changes_data": bool(added or updated or retired),
        "before": sorted(before, key=lambda t: t["name"]),
        "middles": middles,
        "delta": {"added": added, "updated": updated, "retired": retired, "checked": checked, "others": others},
        "after": sorted((_table(cache, frames, v, "存量") for v in after.values()), key=lambda t: t["name"]),
    }


def datasets_first(datasets: list[dict], name: str) -> dict:
    d = next(x for x in datasets if x["name"] == name)
    return {**d["versions"][0], "description": d.get("description", "")}


def _middles(project: Project, step: Step, rev: Revision, cache: DataCache, frames: dict, seen: set[str]) -> list[dict]:
    """中间产物：本轮目录里留下的、没进存量账的**数据文件**（csv / tsv / xlsx / parquet）。

    它们不是「有用的最终文件」（所以不进存量账），但是核对时常要翻——比如一次性的核对清单、行数台账。
    报告、说明卡、决策清单这类 markdown / json / yaml 不在这里：它们不是数据表，在「产物」里看。
    """
    out: list[dict] = []
    files, _ = revision_files(project.root, rev.dir, exclude_revisions=Path(rev.dir) == Path(step.dir))
    for f in files:
        rel = f["path"]
        if rel in seen or data_format(Path(rel)) is None:
            continue
        seen.add(rel)
        entry = _entry(cache, Path(rel).name, rel, "中间产物", "")
        entry["rel"] = f["rel"]
        entry["guide_refs"] = frames.get(posixpath.normpath(rel), [])
        out.append(entry)
    return sorted(out, key=lambda t: t["path"])


def _others(project: Project, step: Step, rev: Revision, cache: DataCache, frames: dict, added: list[dict],
            seen: set[str]) -> list[dict]:
    """这一步产出的非表格产物：说明卡里声明了用途的产物（数据文件补进「新增」）、本轮的用户报告与验收报告。"""
    out: list[dict] = []
    card, _ = load_card(project.root, rev.dir)
    for a in (card or {}).get("artifacts") or []:
        raw = a["path"].split("#")[0]
        rel = posixpath.normpath(posixpath.join(rev.dir, raw)) if not (project.root / raw).exists() else posixpath.normpath(raw)
        if rel in seen:
            continue
        seen.add(rel)
        if data_format(Path(rel)) is not None:
            entry = _entry(cache, Path(rel).name, rel, "新增", a.get("purpose", ""), declared=True)
            entry["guide_refs"] = frames.get(rel, [])
            added.append(entry)
        else:
            out.append({"path": rel, "rel": raw, "kind": a.get("kind", "other"), "kind_label": "说明卡声明的产物",
                        "purpose": a.get("purpose", ""), "exists": (project.root / rel).exists()})
    files, _ = revision_files(project.root, rev.dir, exclude_revisions=Path(rev.dir) == Path(step.dir))
    for f in files:
        if f["kind"] in KIND_LABEL and f["path"] not in seen:
            seen.add(f["path"])
            out.append({"path": f["path"], "rel": f["rel"], "kind": f["kind"], "kind_label": KIND_LABEL[f["kind"]],
                        "purpose": "", "exists": True})
    return out
