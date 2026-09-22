"""知识边界与停止规则。

知识边界：各步现在能说什么、还不能说什么、下一步；尚待裁定的问题；无效 / 无结论 / 失败的尝试（探索记录）。
停止规则：同一步骤同一指标按时间排列（不含结论"无效"的运行），看每次尝试相对"之前最好成绩"的提升；
最近 3 次提升都不到 1% 时提示：边际收益很低，先判断这点提升会不会改变业务决策，再决定停止或转去补数据。
"""

from __future__ import annotations

import re

from ..core.project import Project
from ..core.schemas import STATUS_LABEL, Registry
from ..core.steps import load_card, revisions_of
from ..explain.guide import load_guide

LOWER = re.compile(r"mae|rmse|mse|mape|loss|误差|错误率|偏差", re.I)
HIGHER = re.compile(r"auc|f1|acc|准确|精确|召回|r2|捕获|capture|precision|recall|命中", re.I)
MIN_GAIN = 0.01
WINDOW = 3


def direction(metric: str, goals: dict[str, str]) -> str | None:
    if metric in goals:
        return goals[metric]
    if LOWER.search(metric):
        return "min"
    if HIGHER.search(metric):
        return "max"
    return None


def stop_rules(runs: list[dict], goals: dict[str, str], min_gain: float = MIN_GAIN, window: int = WINDOW) -> list[dict]:
    # 结论"无效"的运行（如有泄漏）不参与：它的指标不能算作最好成绩
    ok = sorted((r for r in runs if r["status"] == "succeeded" and r.get("validity") != "无效"), key=lambda r: r["started_at"])
    out = []
    for step in dict.fromkeys(r["step"] for r in ok):
        step_runs = [r for r in ok if r["step"] == step]
        for metric in dict.fromkeys(m for r in step_runs for m in r["metrics"]):
            series = [r for r in step_runs if r["metrics"].get(metric) is not None]
            if len(series) < 2:
                continue
            d = direction(metric, goals)
            points, best = [], None
            for r in series:
                v = r["metrics"][metric]
                gain = None
                if best is not None and d and best != 0:
                    gain = (best - v) / abs(best) if d == "min" else (v - best) / abs(best)
                if best is None or (d == "min" and v < best) or (d == "max" and v > best):
                    best = v
                points.append({"run_id": r["run_id"], "time": r["started_at"], "value": v, "best": best, "gain": gain,
                               "hypothesis": r.get("hypothesis", "")})
            item = {"step": step, "metric": metric, "direction": d, "points": points}
            if d is None:
                item.update(level="unknown", hint="不知道这个指标越大越好还是越小越好；在 dsflow.yaml 的 metric_goals 里声明后才能判断")
            elif len(series) < window + 1:
                item.update(level="insufficient", hint=f"只有 {len(series)} 次运行，第一次之后的尝试不足 {window} 次，暂不判断")
            else:
                last = [p["gain"] for p in points[-window:]]
                if all(g is not None and g < min_gain for g in last):
                    shown = "、".join(f"{g:+.1%}" for g in last)
                    item.update(level="stop", hint=(
                        f"最近 {window} 次尝试相对之前最好成绩的提升分别是 {shown}，都不到 {min_gain:.0%}。"
                        "继续沿同一方向调整的边际收益很低：先判断这点提升会不会改变业务决策，再决定停止，或者转去补充数据、改进特征。"))
                else:
                    item.update(level="continue", hint=f"最近 {window} 次尝试里仍有提升达到 {min_gain:.0%} 以上")
            out.append(item)
    return out


def knowledge(project: Project, reg: Registry, runs: list[dict], pending: list[dict], goals: dict[str, str]) -> dict:
    """能说 / 不能说取自讲解（guide.yaml 的结论与易错点），说明卡只提供一句话结论。"""
    steps = []
    for step in reg.steps:
        revs = revisions_of(step)
        current = next((r for r in revs if r.id == step.current_revision), revs[-1])
        card, _ = load_card(project.root, current.dir)
        guide, _, _, _ = load_guide(project, step, current)
        brief = (guide or {}).get("brief") or {}
        steps.append({
            "step": step.id, "title": step.title, "status": step.status, "status_label": STATUS_LABEL[step.status],
            "revision": current.id, "has_card": card is not None, "has_guide": guide is not None,
            "headline": card["headline"] if card else "",
            "can_say": [brief["answer"]] if brief.get("answer") else [],
            "cannot_say": list((guide or {}).get("cannot_say") or []),
            "next": brief.get("next") or "",
            "finding": step.finding, "decision": step.decision,
        })
    exploration = [
        {k: r.get(k) for k in ("run_id", "step", "started_at", "status", "validity", "hypothesis", "conclusion", "error")}
        for r in runs if r.get("validity") in ("无效", "无结论") or r["status"] == "failed"
    ]
    return {
        "steps": steps,
        "open_questions": [p for p in pending if p["status"] != "resolved"],
        "exploration": exploration,
        "stop_rules": stop_rules(runs, goals),
    }
