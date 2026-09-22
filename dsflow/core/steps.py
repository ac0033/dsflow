"""步骤工作区的数据：轮次、每轮的文件（按角色分类）、步骤说明卡、实际推进路径。只读。

目录约定：第一轮就是步骤目录本身，之后的轮次在 revisions/rNN_日期_说明/；
主验收在本轮根目录的 acceptance.md（data-science-project skill 的默认名）或 acceptance/<日期>_*/report.md；
讲解在本轮根目录的 guide.yaml；历史操作在 operations/。
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from .schemas import STATUS_LABEL, Registry, Revision, Step, StepCard
from .validate import ValidationIssue

SKIP_DIRS = {".git", ".venv", "__pycache__", ".ipynb_checkpoints", "node_modules", ".dsflow"}
MAX_FILES = 3000
CODE_SUFFIXES = (".py", ".sql", ".r", ".sh", ".ps1")
REPORT_NAMES = {"report.md", "user-report.md", "user-report.qmd", "user-report.html", "user_report.md"}
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def classify(rel: str) -> str:
    """按轮次目录内的相对路径判断文件角色。"""
    parts = rel.lower().split("/")
    name, top = parts[-1], (parts[0] if len(parts) > 1 else "")
    if name == "step_card.yaml":
        return "card"
    if name.endswith(".ipynb"):
        return "notebook"
    if top == "acceptance":
        if name == "report.md" and len(parts) in (2, 3):
            return "acceptance_report"
        return "acceptance_code" if name.endswith(CODE_SUFFIXES) else "acceptance_material"
    if top == "operations":
        return "operation"
    if len(parts) == 1:
        if name == "plan.md":
            return "plan"
        if name == "plan_user.md":
            return "plan_user"
        if name == "approval_record.md":
            return "approval"
        if name in REPORT_NAMES:
            return "report"
        if name == "acceptance.md":
            return "acceptance_report"
        if name == "guide.yaml":
            return "guide"
        if name == "execution_record.md":
            return "execution_record"
    if top == "planning":
        return "approval" if name == "approval_record.md" else "planning"
    if top in ("outputs", "output"):
        return "output"
    if top == "reporting":
        return "evidence"
    if name.endswith(CODE_SUFFIXES):
        return "code"
    if name.endswith(".md"):
        return "doc"
    return "other"


def revisions_of(step: Step) -> list[Revision]:
    """没有登记轮次的步骤视为只有一轮，目录就是步骤目录。"""
    if step.revisions:
        return step.revisions
    return [Revision(id=step.current_revision or "r01", status=step.status, dir=step.dir,
                     acceptance_report=step.acceptance_report)]


def revision_files(root: Path, rev_dir: str, exclude_revisions: bool) -> tuple[list[dict], bool]:
    base = root / rev_dir
    if not base.is_dir():
        return [], False
    out: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = Path(dirpath).relative_to(base).as_posix()
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIRS and not (exclude_revisions and rel_dir == "." and d == "revisions")
        )
        for name in sorted(filenames):
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            full = Path(dirpath) / name
            out.append({"path": full.relative_to(root).as_posix(), "rel": rel,
                        "size": full.stat().st_size, "kind": classify(rel)})
            if len(out) >= MAX_FILES:
                return out, True
    return out, False


def load_card(root: Path, rev_dir: str) -> tuple[dict | None, str | None]:
    path = root / rev_dir / "step_card.yaml"
    if not path.is_file():
        return None, None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return StepCard.model_validate(data).model_dump(), None
    except (yaml.YAMLError, ValidationError) as exc:
        return None, "step_card.yaml 无法解析：" + " ".join(str(exc).split("\n")[:3])


def revision_date(root: Path, rev: Revision) -> tuple[str | None, str | None]:
    """轮次日期：登记的 date → 目录名里的日期 → 主验收目录名里最早的日期 → plan.md 修改时间。"""
    declared = getattr(rev, "date", None)
    if isinstance(declared, str) and _DATE.fullmatch(declared):
        return declared, "注册表"
    m = _DATE.search(Path(rev.dir).name)
    if m:
        return m.group(1), "目录名"
    acceptance = root / rev.dir / "acceptance"
    if acceptance.is_dir():
        dates = sorted(m.group(1) for d in acceptance.iterdir() if d.is_dir() and (m := _DATE.search(d.name)))
        if dates:
            return dates[0], "主验收目录名"
    plan = root / rev.dir / "plan.md"
    if plan.is_file():
        # 精确到秒：和运行记录的时间放在一起排序时，不会因为只有日期而排到当天所有运行之前
        return datetime.fromtimestamp(plan.stat().st_mtime).isoformat(timespec="seconds"), "文件修改时间（推断）"
    return None, None


def card_summary(root: Path, step: Step) -> dict | None:
    """流程图节点上用的摘要：一句话结论 + 前 3 个核心数字 + 前 3 个产物。"""
    current = next((r for r in step.revisions if r.id == step.current_revision), None)
    dirs = [d for d in (current.dir if current else None, step.dir) if d]
    for d in dict.fromkeys(dirs):
        card, _ = load_card(root, d)
        if card:
            return {
                "headline": card["headline"],
                "can_continue": card["can_continue"],
                "numbers": card["core_numbers"][:3],
                "artifacts": [a["path"] for a in card["artifacts"][:3]],
            }
    return None


def step_detail(root: Path, reg: Registry, step_id: str, issues: list[ValidationIssue]) -> dict:
    step = next((s for s in reg.steps if s.id == step_id), None)
    if step is None:
        raise KeyError(step_id)
    revisions = []
    for rev in revisions_of(step):
        files, truncated = revision_files(root, rev.dir, exclude_revisions=Path(rev.dir) == Path(step.dir))
        card, card_error = load_card(root, rev.dir)
        date, date_source = revision_date(root, rev)
        acceptance = sorted((f["path"] for f in files if f["kind"] == "acceptance_report"), reverse=True)
        revisions.append({
            **rev.model_dump(), "status_label": STATUS_LABEL[rev.status], "date": date, "date_source": date_source,
            "files": files, "truncated": truncated, "card": card, "card_error": card_error,
            "acceptance_reports": acceptance, "is_current": rev.id == (step.current_revision or rev.id),
        })
    stage = next((s for s in reg.stages if s.id == step.stage), None)
    return {
        "step": {**step.model_dump(by_alias=True), "status_label": STATUS_LABEL[step.status]},
        "stage": stage.model_dump() if stage else None,
        "revisions": revisions,
        "dependencies_in": [{"step": e.from_, "label": e.label} for e in reg.dependencies or [] if e.to == step_id],
        "dependencies_out": [{"step": e.to, "label": e.label} for e in reg.dependencies or [] if e.from_ == step_id],
        "back_edges": [e.model_dump(by_alias=True) for e in reg.back_edges if step_id in (e.from_, e.to)],
        "revision_loops": [e.model_dump() for e in reg.revision_loops if e.step == step_id],
        "issues": [i.to_dict() for i in issues if i.step == step_id],
    }


RUN_STATUS = {"succeeded": ("done", "运行成功"), "failed": ("stopped", "运行失败"), "running": ("in_progress", "运行中")}


def actual_path(root: Path, reg: Registry, runs: list[dict] | None = None) -> list[dict]:
    """按时间排列的实际推进路径：每个轮次一站，每次运行也是一站，能看出跨阶段的跳跃与回退。"""
    entries = []
    for step in reg.steps:
        for rev in revisions_of(step):
            date, source = revision_date(root, rev)
            entries.append({
                "kind": "revision", "step": step.id, "title": step.title, "stage": step.stage, "order": step.order,
                "revision": rev.id, "status": rev.status, "status_label": STATUS_LABEL[rev.status],
                "date": date, "date_source": source, "summary": rev.summary,
            })
    steps = {s.id: s for s in reg.steps}
    for run in runs or []:
        step = steps.get(run.get("step"))
        if step is None:
            continue
        status, label = RUN_STATUS.get(run.get("status"), ("pending", run.get("status", "")))
        entries.append({
            "kind": "run", "step": step.id, "title": step.title, "stage": step.stage, "order": step.order,
            "revision": run.get("revision") or "", "status": status, "status_label": label,
            "date": run["started_at"], "date_source": "运行记录", "run_id": run["run_id"],
            "validity": run.get("validity"), "summary": run.get("conclusion") or run.get("hypothesis") or "",
        })
    entries.sort(key=lambda e: (e["date"] or "9999-99-99", e["order"], e["revision"]))
    return entries
