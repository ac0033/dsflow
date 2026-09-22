"""以数据表为主线看一个步骤：这一步碰了哪几张表、进来什么样、出去什么样、变了哪些列。

和「讲解」是两条腿：讲解讲 notebook 的每一格在做什么，这里讲数据本身怎么变的。
每张表都能整张打开（前端虚拟滚动），所以要报告它有没有转成 Parquet——没转的先让用户点一下准备。

表从三个地方来：
- **登记的数据集**（`dsflow data add`）：带阶段、上游和产出步骤，构成整个项目的主线；
- **运行记录**：用 `dsflow run` 跑过的步骤，`run.input()` 已经记下它读了哪张表，自动挂上；
- **登记的用途**（`dsflow data link`）：没走过 dsflow run 的老项目（比如只读接入的），靠这个补挂；
- **本轮目录下的数据文件**：自动发现，不需要登记——报告旁边那些 csv 就是这一步的证据；
- **讲解里对照过的表**（guide.yaml 里的 data 视图）：讲解讲到哪张表，这里就能整张打开它，两个板块互相能跳。
"""

from __future__ import annotations

from pathlib import Path

import posixpath

import pyarrow.parquet as pq

from ..core.project import Project
from ..core.schemas import Registry, Revision, Step
from ..core.steps import revision_files, revisions_of
from ..tracking.store import RunStore
from .cache import DataCache
from .datasets import STAGE_LABEL, DatasetStore
from .engine import DataError, connect, scan
from .files import data_format

ROLE_ORDER = {"输入": 0, "产出": 1, "核对": 2, "读取": 3, "讲解引用": 4, "本轮产物": 5}


def guide_frames(project: Project, step: Step, rev: Revision) -> dict[str, list[dict]]:
    """讲解（guide.yaml）里配了数据视图的文件 → 它在讲解里的位置：第几段、哪一格、给人看什么。

    路径按讲解里的写法（相对项目根目录）归一，和登记的数据集、本轮目录里的文件对得上。
    """
    from ..explain.guide import load_guide

    guide, _, _, _ = load_guide(project, step, rev)
    out: dict[str, list[dict]] = {}
    for pi, part in enumerate((guide or {}).get("parts") or [], 1):
        for note in part.get("cells") or []:
            data = note.get("data") or {}
            for frame in data.get("frames") or []:
                rel = posixpath.normpath(frame["file"])
                out.setdefault(rel, []).append({
                    "part": pi, "question": part.get("question") or "", "cell_title": note.get("title") or "",
                    "title": data.get("title") or "", "label": frame.get("label") or "",
                    "caption": frame.get("caption") or "", "columns": list(frame.get("columns") or []),
                })
    return out


def _columns_of(cache: DataCache, rel: str) -> list[str] | None:
    """列名。没转成 Parquet 的返回 None——不为了列名去做几分钟的整表转换。"""
    try:
        parquet = cache.parquet_if_ready(rel)
    except (FileNotFoundError, DataError):
        return None
    if parquet is None:
        return None
    return [r[0] for r in connect().execute(f"DESCRIBE SELECT * FROM {scan(parquet)}").fetchall()]


def _shape(cache: DataCache, rel: str) -> dict:
    """整张表的规模与是否可以直接打开。"""
    out: dict = {"ready": False, "rows": None, "columns": None, "size": None, "missing": False}
    try:
        _, path, fmt = cache.source(rel)
    except (FileNotFoundError, DataError):
        out["missing"] = True
        return out
    out["size"] = path.stat().st_size
    out["format"] = fmt
    try:
        parquet = cache.parquet_if_ready(rel)
    except (FileNotFoundError, DataError):
        parquet = None
    if parquet is not None:
        meta = pq.ParquetFile(parquet).metadata
        out.update(ready=True, rows=meta.num_rows, columns=meta.num_columns)
    return out


def _version_parquet(cache: DataCache, v: dict, exact: bool) -> Path | None:
    """某个登记版本当时的 Parquet。

    先按登记时的哈希查缓存——源文件后来被新一版覆盖了，旧版本的行列数照样查得到。
    查不到时：`exact=True`（问的就是旧版本）宁可说不知道；`exact=False`（问的是现在这一版）就读源文件本身。
    """
    found = cache.parquet_for_sha(v.get("sha256") or "")
    if found is not None:
        return found
    try:
        if cache.known_fingerprint(v["path"]) == v.get("sha256"):
            return cache.parquet_if_ready(v["path"])
        return None if exact else cache.parquet_if_ready(v["path"])
    except (FileNotFoundError, DataError):
        return None


def version_shape(cache: DataCache, v: dict, exact: bool = False) -> dict:
    """某个登记版本的规模。和 `_shape` 的区别：认的是登记时的那一版，不会把后来覆盖上去的那一版数成它。"""
    out: dict = {"ready": False, "rows": None, "columns": None, "size": None, "missing": False}
    try:
        _, path, fmt = cache.source(v["path"])
        out["size"] = path.stat().st_size
        out["format"] = fmt
    except (FileNotFoundError, DataError):
        out["missing"] = True
    parquet = _version_parquet(cache, v, exact)
    if parquet is not None:
        meta = pq.ParquetFile(parquet).metadata
        out.update(ready=True, rows=meta.num_rows, columns=meta.num_columns)
    return out


def version_columns(cache: DataCache, v: dict, exact: bool = False) -> list[str] | None:
    """某个登记版本当时的列名；查不到那一版就返回 None，不拿别的版本顶替。"""
    parquet = _version_parquet(cache, v, exact)
    if parquet is None:
        return None
    return [r[0] for r in connect().execute(f"DESCRIBE SELECT * FROM {scan(parquet)}").fetchall()]


def diff_columns(before: list[str] | None, after: list[str] | None) -> dict:
    """两张表的列差。两边都得先转成 Parquet 才比得了，比不了就如实说比不了。"""
    if before is None or after is None:
        return {"known": False, "added": [], "removed": [], "kept": 0}
    sb, sa = set(before), set(after)
    return {"known": True, "added": [c for c in after if c not in sb],
            "removed": [c for c in before if c not in sa], "kept": len(sa & sb)}


# 名字下面那行小字：这份数据的简要介绍。没写介绍的如实说没写，不拿路径顶替。
NO_NOTE = "还没有写这份数据的介绍。"


def _entry(cache: DataCache, name: str, rel: str, role: str, note: str = "", **extra) -> dict:
    text = (note or "").strip()
    return {"name": name, "path": rel, "role": role, "note": text or NO_NOTE, "note_missing": not text,
            "guide_refs": [], **_shape(cache, rel), **extra}


# 只列"读的人会想点开"的那几类；代码与 notebook 有自己的标签，不在这里重复
KIND_LABEL = {"report": "用户报告", "acceptance_report": "验收报告", "plan_user": "计划（给你看的）",
              "plan": "计划", "approval": "审批记录", "execution_record": "执行记录", "card": "说明卡"}


def _revision_files(project: Project, step: Step, rev: Revision) -> tuple[list[dict], list[dict]]:
    """本轮目录下的（数据文件, 非表格产物）。数据文件能直接打开；其余的列出来带个链接，别让人再去别的标签找。"""
    files, _ = revision_files(project.root, rev.dir, exclude_revisions=Path(rev.dir) == Path(step.dir))
    tables, others = [], []
    for f in files:
        if data_format(Path(f["path"])) is not None:
            tables.append({"path": f["path"], "rel": f["rel"], "size": f["size"]})
        elif f["kind"] in KIND_LABEL:
            others.append({"path": f["path"], "rel": f["rel"], "size": f["size"],
                           "kind": f["kind"], "kind_label": KIND_LABEL[f["kind"]]})
    return sorted(tables, key=lambda x: x["rel"]), sorted(others, key=lambda x: (x["kind"], x["rel"]))


def step_tables(project: Project, reg: Registry, step_id: str, rev_id: str | None = None) -> dict:
    """一个步骤的数据主线：输入 → 产出，外加它核对过的表和本轮留下的数据文件。"""
    step = next((s for s in reg.steps if s.id == step_id), None)
    if step is None:
        raise KeyError(f"步骤 {step_id} 不存在")
    revs = revisions_of(step)
    rev = next((r for r in revs if r.id == (rev_id or step.current_revision)), revs[-1])

    cache = DataCache(project)
    chain = DatasetStore(project).chain()
    by_name = {c["name"]: c for c in chain}

    produced = [c for c in chain if c["produced_by"] == step_id]
    made = {c["name"] for c in produced}
    inputs: dict[str, dict] = {}
    for child in produced:
        for parent in child["parents"]:
            # 本步自己产出的表不算输入——它是中间结果，列在产出里就够了
            if parent in by_name and parent not in inputs and parent not in made:
                inputs[parent] = by_name[parent]
    used = {c["name"]: role for c in chain for u in c["used_by"] if (role := u["role"]) and u["step"] == step_id}
    # 用 dsflow run 跑过的步骤，run.input() 已经记下它读了哪张表，不必再手工挂
    for run in RunStore(project).list(step_id):
        for ref in run.get("inputs") or []:
            if ref.get("name") in by_name:
                used.setdefault(ref["name"], "读取")

    tables: list[dict] = []
    for c in inputs.values():
        tables.append(_entry(cache, c["name"], c["path"], "输入", c["description"],
                             stage=c["stage"], stage_label=c["stage_label"], version=c["version"]))
    for c in produced:
        # 和哪张上游表比：取第一张已经转好的，比不了就如实说比不了
        base, before = None, None
        for name in c["parents"]:
            cols = _columns_of(cache, by_name[name]["path"]) if name in by_name else None
            if cols is not None:
                base, before = name, cols
                break
        tables.append(_entry(cache, c["name"], c["path"], "产出", c["description"],
                             stage=c["stage"], stage_label=c["stage_label"], version=c["version"],
                             parents=c["parents"], diff_base=base,
                             diff=diff_columns(before, _columns_of(cache, c["path"]))))
    seen = {t["path"] for t in tables}
    for name, role in sorted(used.items()):
        c = by_name[name]
        if c["path"] in seen:
            continue
        seen.add(c["path"])
        tables.append(_entry(cache, c["name"], c["path"], role, c["description"],
                             stage=c["stage"], stage_label=c["stage_label"], version=c["version"]))
    rev_tables, others = _revision_files(project, step, rev)
    for f in rev_tables:
        if f["path"] in seen:
            continue
        seen.add(f["path"])
        tables.append(_entry(cache, Path(f["rel"]).name, f["path"], "本轮产物"))

    # 讲解里对照过的表：已经在上面的挂上「讲解第几段」；没在的补一张卡，名字用讲解给它起的那个
    frames = guide_frames(project, step, rev)
    for t in tables:
        t["guide_refs"] = frames.get(posixpath.normpath(t["path"]), [])
    for rel, refs in frames.items():
        if rel in seen:
            continue
        seen.add(rel)
        tables.append(_entry(cache, refs[0]["title"] or Path(rel).name, rel, "讲解引用", refs[0]["caption"], guide_refs=refs))
    tables.sort(key=lambda t: (ROLE_ORDER.get(t["role"], 9), t["name"]))

    changes = any(t["role"] == "产出" for t in tables)
    return {
        "step": step.id,
        "revision": rev.id,
        "revision_dir": rev.dir,
        "changes_data": changes,
        "tables": tables,
        "others": others,
        "chain": chain,
        "stage_labels": STAGE_LABEL,
    }
