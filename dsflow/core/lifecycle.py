"""把注册表投影成前端流程图所需的节点与边（对应 build_lifecycle.py 的 build()）。

边只来自显式登记的 dependencies / back_edges / revision_loops，绝不按编号推导。
"""

from __future__ import annotations

from pathlib import Path

from .schemas import STATUS_LABEL, Registry, Step
from .validate import ValidationIssue


def report_path_for(step: Step, root: Path) -> str:
    """节点点击后打开的报告：主验收报告优先，否则当前轮次的 report.md，再否则步骤根目录的 report.md。"""
    report_dir = step.dir
    if step.current_revision:
        revision = next((r for r in step.revisions if r.id == step.current_revision), None)
        if revision and (root / revision.dir / "report.md").exists():
            report_dir = revision.dir
    return step.acceptance_report or f"{report_dir}/report.md"


def build_graph(reg: Registry, root: Path, issues: list[ValidationIssue] | None = None,
                runs: list[dict] | None = None) -> dict:
    from .steps import actual_path, card_summary

    root = Path(root)
    issue_count: dict[str, int] = {}
    for issue in issues or []:
        if issue.step:
            issue_count[issue.step] = issue_count.get(issue.step, 0) + 1
    nodes = []
    for step in sorted(reg.steps, key=lambda s: s.order):
        node = step.model_dump(by_alias=True)
        report_path = report_path_for(step, root)
        node.update(
            status_label=STATUS_LABEL[step.status],
            report_path=report_path,
            report_available=(root / report_path).is_file(),
            revision_count=len(step.revisions),
            card=card_summary(root, step),
            issue_count=issue_count.get(step.id, 0),
        )
        nodes.append(node)

    edges = []
    for e in reg.dependencies or []:
        edges.append({"from": e.from_, "to": e.to, "type": "dependency", "label": e.label})
    for e in reg.back_edges:
        edges.append({"from": e.from_, "to": e.to, "type": "back", "label": e.label, "loop": e.loop})
    for e in reg.revision_loops:
        edges.append({
            "from": e.step, "to": e.step, "type": "revision_loop", "label": e.label,
            "from_revision": e.from_revision, "to_revision": e.to_revision,
        })

    return {
        "title": reg.title,
        "stages": [s.model_dump() for s in reg.stages],
        "nodes": nodes,
        "edges": edges,
        "groups": {k: g.model_dump() for k, g in reg.groups.items()},
        "notes": reg.notes,
        "path": actual_path(root, reg, runs),
    }
