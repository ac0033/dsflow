"""一列的来历：这一列为什么新增 / 消失 / 取值变了，讲解里哪一段说过它，notebook 里哪一格动了它。

数据层只知道"列变了"，说不出"为什么变"——那句话在讲解里。这里把两边接起来：
拿列名去讲解的每一段旁注和 notebook 的每一格源码里找，找到就把出处（第几段、第几格、原话）交给界面，
界面据此让列名可以点开看说明，并跳到讲解里的那一格。找不到就如实说找不到，不猜一个理由。
"""

from __future__ import annotations

import re

from ..core.project import Project
from ..core.schemas import Revision, Step
from .guide import cells_from_text, load_guide, read_cells

MAX_PER_COLUMN = 4      # 一列最多给几条出处，多了界面读不完
QUOTE_LIMIT = 180       # 引用的那句话最多多少字
_SENTENCE = re.compile(r"[^。！？；\n]*[。！？；\n]?")


def _sentence_with(text: str, name: str) -> str:
    """取文字里包含这个列名的那一句；没有就返回空。"""
    if not text or name not in text:
        return ""
    for piece in _SENTENCE.findall(text):
        if name in piece:
            return piece.strip()[:QUOTE_LIMIT]
    return text.strip()[:QUOTE_LIMIT]


def _cell_numbers(note: dict) -> list[int]:
    cell = note.get("cell")
    if isinstance(cell, int):
        return [cell]
    return [c for c in (cell or []) if isinstance(c, int)]


def _notebook_lines(project: Project, rev: Revision, guide: dict) -> dict[int, tuple[str, list[str]]]:
    """notebook 每一格的（类型, 源码行）；读不出来就当没有，不让界面因此报错。"""
    name = guide.get("notebook")
    if not name:
        return {}
    rel = f"{rev.dir}/{name}" if not name.startswith(rev.dir) else name
    try:
        cells = read_cells(project.resolve(rel))
    except Exception:  # noqa: BLE001 - notebook 缺失或格式不对时退回"没有代码出处"
        try:
            cells = cells_from_text(project.read_text(rel)["content"])
        except Exception:  # noqa: BLE001
            return {}
    return {i: (cell.get("type") or "code", (cell.get("source") or "").splitlines()) for i, cell in enumerate(cells, 1)}


def column_notes(project: Project, step: Step, rev: Revision, columns: list[str]) -> dict[str, list[dict]]:
    """每一列的出处：先看讲解里哪一段旁注提到它，再看 notebook 里哪一格的代码写到它。

    返回 {列名: [{source, part, cell, where, title, quote}]}，按"讲解在前、代码在后"排。
    """
    guide, _, _, _ = load_guide(project, step, rev)
    if not guide:
        return {name: [] for name in columns}
    code = _notebook_lines(project, rev, guide)
    out: dict[str, list[dict]] = {name: [] for name in columns}

    for pi, part in enumerate(guide.get("parts") or [], 1):
        for ci, note in enumerate(part.get("cells") or [], 1):
            numbers = _cell_numbers(note)
            texts = [note.get("title") or "", note.get("what") or "", note.get("why") or "", note.get("read") or ""]
            texts += [line.get("note") or "" for line in note.get("lines") or []]
            data = note.get("data") or {}
            frames = data.get("frames") or []
            texts += [data.get("title") or "", *(f.get("caption") or "" for f in frames)]
            marked = {c for f in frames for c in (f.get("columns") or [])}
            marked |= {c for f in frames for c in ((f.get("mark") or {}).get("columns") or [])}
            texts += [(f.get("mark") or {}).get("note") or "" for f in frames]
            joined = "\n".join(t for t in texts if t)
            for name in columns:
                if len(out[name]) >= MAX_PER_COLUMN:
                    continue
                quote = _sentence_with(joined, name)
                if not quote and name not in marked:
                    continue
                out[name].append({
                    "source": "讲解",
                    "part": pi,
                    "cell": numbers[0] if numbers else None,
                    "where": f"问题 {pi} · 第 {ci} 条" + (f"（单元格 {numbers[0]}）" if numbers else ""),
                    "title": note.get("title") or part.get("question") or "",
                    "quote": quote or f"数据视图里专门点出了「{name}」这一列。",
                })

    for number, (kind, lines) in code.items():
        label = "代码" if kind == "code" else "说明"
        for name in columns:
            if len(out[name]) >= MAX_PER_COLUMN:
                continue
            hit = next((ln.strip() for ln in lines if name in ln), "")
            if not hit or any(r["source"] != "讲解" and r["cell"] == number for r in out[name]):
                continue
            out[name].append({
                "source": label, "part": None, "cell": number,
                "where": f"单元格 {number} 的{label}", "title": "", "quote": hit[:QUOTE_LIMIT],
            })
    return out
