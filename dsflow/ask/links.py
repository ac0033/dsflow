"""答案里提到的东西 → 页面上的位置：数据文件跳到数据选项卡，单元格跳到讲解的那一格。

模型回答时会写出文件名（`orders_clean.parquet`）和格号（「单元格 4」）。这里把它们认出来，
核对确实存在，再告诉界面该跳到哪一页——跳错地方比不跳更糟，所以对不上的一律不给链接。
"""

from __future__ import annotations

import re

from pathlib import Path

from ..core.project import Project
from ..core.schemas import Registry
from ..data.files import data_format

MAX_LINKS = 8
SUFFIXES = ("csv", "tsv", "xlsx", "parquet", "ipynb", "py", "md", "json", "yaml", "yml", "txt", "png", "svg")
_PATH = re.compile(r"[\w一-鿿][\w一-鿿./\\-]*\.(?:" + "|".join(SUFFIXES) + r")\b")
_CELL = re.compile(r"单元格\s*(\d{1,3})|第\s*(\d{1,3})\s*个?单元格")


def _candidates(project: Project, reg: Registry | None, step_id: str | None) -> dict[str, str]:
    """本项目里能被答案提到的文件：登记过的数据集 + 这一步本轮的文件。键是文件名，值是项目内路径。"""
    from ..core.steps import revision_files, revisions_of
    from ..data.datasets import DatasetStore

    out: dict[str, str] = {}
    for d in DatasetStore(project).list():
        for v in d["versions"]:
            out.setdefault(Path(v["path"]).name, v["path"])
        out.setdefault(d["name"], d["versions"][-1]["path"])
    step = next((s for s in (reg.steps if reg else []) if s.id == step_id), None)
    if step is not None:
        revs = revisions_of(step)
        for rev in revs[-2:]:
            files, _ = revision_files(project.root, rev.dir, exclude_revisions=False)
            for f in files:
                out.setdefault(Path(f["path"]).name, f["path"])
    return out


def _owner_step(reg: Registry | None, path: str) -> str | None:
    """这个文件属于哪一步：落在某个步骤目录下就算那一步，数据选项卡才打得开它。"""
    for s in sorted((reg.steps if reg else []), key=lambda x: len(x.dir), reverse=True):
        if s.dir and path.startswith(s.dir.rstrip("/") + "/"):
            return s.id
    return None


def find_links(project: Project, reg: Registry | None, answer: str, step_id: str | None) -> list[dict]:
    """答案里提到、并且项目里确实存在的东西：数据文件、代码与文档、notebook 的某一格。"""
    if not answer:
        return []
    known = _candidates(project, reg, step_id)
    out: list[dict] = []
    seen: set[str] = set()

    for m in _PATH.finditer(answer):
        token = m.group(0).replace("\\", "/").strip("./")
        rel = token if (project.root / token).is_file() else known.get(Path(token).name, "")
        if not rel or rel in seen:
            continue
        seen.add(rel)
        kind = "data" if data_format(Path(rel)) is not None else "file"
        out.append({"kind": kind, "label": Path(rel).name, "path": rel, "step": _owner_step(reg, rel), "cell": None})
        if len(out) >= MAX_LINKS:
            return out

    for m in _CELL.finditer(answer):
        number = int(m.group(1) or m.group(2))
        key = f"cell-{number}"
        if not step_id or key in seen:
            continue
        seen.add(key)
        out.append({"kind": "cell", "label": f"单元格 {number}", "path": None, "step": step_id, "cell": number})
        if len(out) >= MAX_LINKS:
            break
    return out
