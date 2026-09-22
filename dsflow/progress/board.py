"""项目看板：先说整体进度和需要你处理的事，再给告警、各阶段进度、迭代情况和最近动态。"""

from __future__ import annotations

from ..core.project import Project
from ..core.schemas import STATUS_LABEL, Registry
from ..core.steps import revisions_of
from ..core.validate import ValidationIssue
from ..delivery.models import ModelStore
from .activity import activity
from .alerts import compute_alerts
from .tracker import TrackerStore, project_pending

SEVERITY = {"高": 0, "中": 1, "低": 2}


def build_board(project: Project, reg: Registry, issues: list[ValidationIssue], runs: list[dict]) -> dict:
    tracker = TrackerStore(project)
    items = {k: tracker.list(k) for k in ("issues", "decisions", "pending")}
    pending = [*items["pending"], *project_pending(project.root, reg)]

    counts: dict[str, int] = {}
    for s in reg.steps:
        counts[s.status] = counts.get(s.status, 0) + 1
    stages = []
    for stage in reg.stages:
        steps = [s for s in reg.steps if s.stage == stage.id]
        stages.append({"id": stage.id, "name": stage.name, "color": stage.color, "total": len(steps),
                       "done": sum(1 for s in steps if s.status == "done"),
                       "active": sum(1 for s in steps if s.status in ("in_progress", "awaiting_acceptance", "partial", "pending_approval"))})

    def brief(step) -> dict:
        revs = revisions_of(step)
        current = next((r for r in revs if r.id == step.current_revision), revs[-1])
        return {"step": step.id, "title": step.title, "status": step.status, "status_label": STATUS_LABEL[step.status],
                "revision": current.id, "summary": current.summary or step.finding or step.op}

    attention = {
        "pending_approval": [brief(s) for s in reg.steps if s.status == "pending_approval"],
        "awaiting_acceptance": [brief(s) for s in reg.steps if s.status == "awaiting_acceptance"],
        "unfinished": [brief(s) for s in reg.steps if s.status in ("in_progress", "partial", "stopped")],
        "blocking_decisions": [p for p in pending if p["status"] != "resolved" and p.get("blocking")],
        "open_issues": sorted((i for i in items["issues"] if i["status"] == "open"),
                              key=lambda i: (not i.get("blocking"), SEVERITY.get(i.get("severity", "中"), 1))),
    }

    loops: dict[str, int] = {}
    for e in reg.revision_loops:
        loops[e.step] = loops.get(e.step, 0) + 1
    iterations = []
    for s in reg.steps:
        step_runs = [r for r in runs if r["step"] == s.id]
        iterations.append({
            "step": s.id, "title": s.title, "status": s.status, "status_label": STATUS_LABEL[s.status],
            "revisions": len(s.revisions) or 1, "loops": loops.get(s.id, 0),
            "back_edges": sum(1 for e in reg.back_edges if s.id in (e.from_, e.to)),
            "runs": len(step_runs), "succeeded": sum(1 for r in step_runs if r["status"] == "succeeded"),
            "failed": sum(1 for r in step_runs if r["status"] == "failed"),
            "invalid": sum(1 for r in step_runs if r.get("validity") in ("无效", "无结论")),
            "last_run": step_runs[0]["started_at"] if step_runs else None,
        })

    model_counts: dict[str, int] = {}
    for m in ModelStore(project).list():
        for v in m["versions"]:
            model_counts[v["status"]] = model_counts.get(v["status"], 0) + 1

    return {
        "total_steps": len(reg.steps),
        "model_counts": model_counts,
        "status_counts": counts,
        "notes": reg.notes,
        "stages": stages,
        "attention": attention,
        "alerts": compute_alerts(project, reg, issues, runs),
        "iterations": iterations,
        "activity": activity(project.root, reg, runs, items),
        "tracker_counts": {
            "open_issues": sum(1 for i in items["issues"] if i["status"] == "open"),
            "decisions": len(items["decisions"]),
            "unresolved_pending": sum(1 for p in pending if p["status"] != "resolved"),
        },
    }
