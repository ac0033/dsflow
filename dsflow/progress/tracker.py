"""问题、决策、待决事项：在界面上增改，写回 <状态目录>/{issues,decisions,pending}.json。

只读接入的项目写到平台目录；项目文件里已有的待决事项（如 decisions_required.json）只读显示并注明出处。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from ..core.project import Project
from ..core.schemas import Decision, Issue, PendingDecision, Registry
from ..core.steps import revisions_of
from ..data.cache import read_json, write_json

KINDS = {"issues": (Issue, "Q"), "decisions": (Decision, "J"), "pending": (PendingDecision, "P")}
RESOLVED = {"resolved", "已解决", "已确认", "已裁定", "closed", "done"}


class TrackerError(Exception):
    pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class TrackerStore:
    def __init__(self, project: Project):
        self.project = project
        self.dir = project.state_dir()

    def _path(self, kind: str) -> Path:
        if kind not in KINDS:
            raise TrackerError(f"不认识的类别：{kind}（可选 issues / decisions / pending）")
        return self.dir / f"{kind}.json"

    def list(self, kind: str) -> list[dict]:
        return read_json(self._path(kind), [])

    def _validate(self, kind: str, item: dict) -> dict:
        try:
            return KINDS[kind][0].model_validate(item).model_dump()
        except ValidationError as exc:
            raise TrackerError("内容不完整：" + "；".join(f"{'.'.join(map(str, e['loc']))} {e['msg']}" for e in exc.errors())) from exc

    def create(self, kind: str, data: dict) -> dict:
        items = self.list(kind)
        prefix = KINDS[kind][1]
        n = max((int(re.sub(r"\D", "", i["id"]) or 0) for i in items), default=0) + 1
        now = _now()
        base = {"id": f"{prefix}{n}", "created_at": now}
        if kind == "decisions":
            base["date"] = now[:10]
        item = self._validate(kind, {**base, **{k: v for k, v in data.items() if k not in ("id", "created_at")}})
        write_json(self._path(kind), [*items, item])
        return item

    def update(self, kind: str, item_id: str, patch: dict) -> dict:
        items = self.list(kind)
        idx = next((i for i, x in enumerate(items) if x["id"] == item_id), None)
        if idx is None:
            raise KeyError(item_id)
        merged = {**items[idx], **{k: v for k, v in patch.items() if k not in ("id", "created_at")}}
        if kind in ("issues", "pending"):
            done = merged.get("status") == "resolved"
            merged["resolved_at"] = (merged.get("resolved_at") or _now()) if done else None
        items[idx] = self._validate(kind, merged)
        write_json(self._path(kind), items)
        return items[idx]

    def delete(self, kind: str, item_id: str) -> bool:
        items = self.list(kind)
        kept = [x for x in items if x["id"] != item_id]
        write_json(self._path(kind), kept)
        return len(kept) != len(items)


def _pending_file(root: Path, step, rev) -> Path | None:
    base = root / rev.dir
    if not base.is_dir():
        return None
    nested = Path(rev.dir) == Path(step.dir)
    found = sorted(
        p for p in base.rglob("decisions_required.json")
        if not (nested and p.relative_to(base).parts[0] == "revisions")
    )
    preferred = [p for p in found if p.parent.name == "outputs"]
    return (preferred or found or [None])[0]


def project_pending(root: Path, reg: Registry) -> list[dict]:
    """读项目文件里已有的待决事项（decisions_required.json），每个步骤取当前轮次那份；没有就往前找。"""
    out = []
    for step in reg.steps:
        revs = revisions_of(step)
        current = next((r for r in revs if r.id == step.current_revision), revs[-1])
        for rev in [current, *reversed([r for r in revs if r is not current])]:
            path = _pending_file(root, step, rev)
            if path is None:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                break
            items = data if isinstance(data, list) else (data.get("待决事项") or data.get("items") or data.get("decisions") or [])
            rel = path.relative_to(root).as_posix()
            for it in items:
                if not isinstance(it, dict):
                    continue
                status = str(it.get("状态") or it.get("status") or "unresolved")
                out.append({
                    "id": str(it.get("id") or it.get("编号") or ""),
                    "question": it.get("问题") or it.get("question") or it.get("事项") or "",
                    "recommendation": it.get("推荐答案") or it.get("recommendation") or "",
                    "basis": it.get("依据") or it.get("basis") or "",
                    "alternatives": it.get("备选差异") or it.get("alternatives") or "",
                    "impact": it.get("影响范围") or it.get("impact") or "",
                    "blocking": bool(it.get("是否阻塞后续执行", it.get("blocking", False))),
                    "status": "resolved" if status.lower() in RESOLVED else "unresolved",
                    "step": step.id, "revision": rev.id, "source": rel,
                })
            break
    return out
