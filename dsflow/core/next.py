"""`dsflow next`：任何 agent 一条命令知道项目在哪一步、这一步缺什么文件、下一步该做什么。只读。

判断只看注册表状态和本轮目录里有没有对应角色的文件，不看内容对不对：
pending → 写计划；pending_approval → 等审批；in_progress → 执行并落盘；
awaiting_acceptance 没有验收报告 → 主 agent 验收；有验收报告 → 等用户确认。

另外每次都带上两样东西（dsflow/core/rules.py 里的工作规矩）：`environment` 是分析环境的快检查，
项目一步都还没开始、环境又没准备好时，环节就是 preflight——先把环境补齐再写第一份计划；`rules` 是
每个环节都要守的规矩，让只调 next 的 agent 也读得到。
"""

from __future__ import annotations

from pathlib import Path

from .project import Project
from .rules import brief as rules_brief
from .schemas import STATUS_LABEL, Registry, Revision, Step
from .steps import revision_files, revisions_of
from .validate import ValidationIssue


def read_record(project, rev):
    from .approval import read_record as _read

    return _read(project, rev)

ACTIVE = ("pending_approval", "in_progress", "awaiting_acceptance", "partial")
ROLES = ("plan", "approval", "notebook", "report", "card", "guide", "acceptance_report")
ROLE_FILE = {"plan": "plan.md", "approval": "approval_record.md", "notebook": "nb_<步骤>.ipynb", "report": "report.md",
             "card": "step_card.yaml", "guide": "guide.yaml", "acceptance_report": "acceptance.md"}
EXECUTION_ROLES = ("notebook", "report", "card", "guide")


def focus_step(reg: Registry, step_id: str | None = None) -> Step | None:
    """要处理的那一步：指定的；否则顺序最靠前的进行中步骤；否则第一个未开始的；都没有就是 None。"""
    if step_id:
        step = next((s for s in reg.steps if s.id == step_id), None)
        if step is None:
            raise KeyError(step_id)
        return step
    ordered = sorted(reg.steps, key=lambda s: s.order)
    return (next((s for s in ordered if s.status in ACTIVE), None)
            or next((s for s in ordered if s.status == "pending"), None))


def current_revision(step: Step) -> Revision:
    revs = revisions_of(step)
    return next((r for r in revs if r.id == step.current_revision), revs[-1])


def role_files(project: Project, step: Step, rev: Revision) -> dict[str, str | None]:
    """本轮目录里各角色文件的路径（相对项目根目录）；没有的是 None。只读项目的讲解可能在平台目录。"""
    from ..explain.guide import load_guide  # 放在函数里：explain 依赖 core，反过来不能在模块顶层引用

    files, _ = revision_files(project.root, rev.dir, exclude_revisions=Path(rev.dir) == Path(step.dir))
    out: dict[str, str | None] = {role: None for role in ROLES}
    for f in files:
        kind = f["kind"]
        if kind in out and out[kind] is None:
            out[kind] = f["path"]
    if out["acceptance_report"] is None and (rev.acceptance_report or step.acceptance_report):
        out["acceptance_report"] = rev.acceptance_report or step.acceptance_report
    if out["guide"] is None:
        guide, _, path, _ = load_guide(project, step, rev)
        if guide and path is not None:
            out["guide"] = path.as_posix()
    return out


def _phase(step: Step, files: dict[str, str | None]) -> tuple[str, list[str], list[str], list[str]]:
    """（阶段, 缺的文件, 该做的事, 该跑的命令）。"""
    sid, status = step.id, step.status
    if status == "pending":
        return "plan", [], [
            "主 agent 写 plan.md：为什么做这一步、输入是什么、准备怎样处理、生成什么产物、验收标准和停止条件。",
            "一步是一个完整独立的单元：产物能被下一步直接使用，验收标准只看本步产物就能核对；写计划时发现这一步既要做这个又要做那个，就拆成两步各自登记。",
            "写完把注册表里这一步的状态改为 pending_approval，然后等用户审批。",
            "主 agent 与执行 agent 是两个角色：用户没有另行安排时，这两个角色都由你担任。",
        ], ["dsflow validate ."]
    if status == "pending_approval":
        missing = [ROLE_FILE["plan"]] if files["plan"] is None else []
        return "await_approval", missing, [
            "等用户审批计划：用户在平台点「通过 / 退回」，或在对话里表态后由主 agent 运行 dsflow approve / reject 记录原话。",
            "主 agent 在后台运行 dsflow await，命令退出就是审批到了；没有审批不执行。",
        ], [f"dsflow await . {sid} --timeout 7200", f"dsflow approve . {sid} --note \"<用户原话>\""]
    if status == "in_progress":
        missing = [ROLE_FILE[r] for r in EXECUTION_ROLES if files[r] is None]
        return "execute", missing, [
            "执行 agent 执行本步的 notebook，每次运行都用 dsflow run 记录（假设、结论、有效性）。",
            "执行 agent 写 report.md（用户报告）、step_card.yaml（说明卡）和 guide.yaml（讲解初稿），并登记产出的表。",
            "validate 与 check 通过后，把注册表里这一步的状态改为 awaiting_acceptance。",
        ], [
            f"dsflow run {sid} -p . -- python -m dsflow.tracking.notebook <本轮目录>/nb_{sid}.ipynb",
            f"dsflow guide init . {sid}", "dsflow validate .", f"dsflow check . --step {sid}",
        ]
    if status == "awaiting_acceptance":
        if files["acceptance_report"] is None:
            return "acceptance", [ROLE_FILE["acceptance_report"]], [
                "主 agent 从实际产物独立核对操作、数据变化、关键结果和验收标准，写 acceptance.md 说明为什么通过或未通过。",
                "主 agent 运行 guide check 与 guide lint 核对讲解，不通过就退回执行 agent（兼任时就是自己）修改。",
            ], [f"dsflow guide check . --step {sid}", f"dsflow guide lint . --step {sid}", f"dsflow check . --step {sid}"]
        return "await_confirmation", [], [
            "等用户理解并确认：用户在平台点「确认完成」，或在对话里表态后由主 agent 运行 dsflow confirm 记录原话。",
            "主 agent 在后台运行 dsflow await，命令退出就是确认到了；用户确认之前不把状态改为 done，也不制定下一步计划。",
        ], [f"dsflow await . {sid} --timeout 7200", f"dsflow confirm . {sid} --note \"<用户原话>\""]
    if status == "partial":
        return "next_step", [], [
            "这一步标为部分完成：要么开新轮次在原来的基础上递进，要么为下一步制定计划。",
        ], []
    return "next_step", [], ["这一步已经结束；为下一步制定计划。"], []


def environment(project: Project) -> dict:
    """分析环境的快检查（只看目录和文件）。只读接入的项目平台不在它的目录里建环境，所以不检查。"""
    from ..env import quick_check

    if project.readonly:
        return {"ready": True, "checked": False, "detail": "这个项目是只读接入的，平台不在它的目录里建分析环境，所以不检查。", "fix": ""}
    return {**quick_check(project.root), "checked": True}


def _not_started(reg: Registry) -> bool:
    """项目一步都还没开始：所有步骤都停在未开始。"""
    return all(s.status == "pending" for s in reg.steps)


def next_action(project: Project, reg: Registry, issues: list[ValidationIssue], step_id: str | None = None) -> dict:
    step = focus_step(reg, step_id)
    attention = {
        "pending_approval": [{"id": s.id, "title": s.title} for s in reg.steps if s.status == "pending_approval"],
        "awaiting_acceptance": [{"id": s.id, "title": s.title} for s in reg.steps if s.status == "awaiting_acceptance"],
        "in_progress": [{"id": s.id, "title": s.title} for s in reg.steps if s.status == "in_progress"],
    }
    env = environment(project)
    base = {"project": {"id": project.id, "root": project.root.as_posix(), "name": project.name, "readonly": project.readonly},
            "attention": attention, "environment": env, "rules": rules_brief()}
    if step is None:
        blank = not reg.steps
        todo = (["项目里还没有登记步骤：先提出阶段划分，再用 step_add 一步一步登记。"] if blank
                else ["所有步骤都已结束；要继续就在注册表里登记新的步骤。"])
        todo.append("一步是一个完整独立的单元：有自己的输入、自己的产物、自己能核对的验收标准；不要把一个阶段的操作堆成一步，也不要把一个操作拆成三步。")
        phase, commands = "all_done", []
        if blank and not env["ready"]:
            phase = "preflight"
            todo = [f"分析环境还没准备好：{env['detail']}",
                    "先调 env_check 看清楚缺哪一件，再调 env_prepare 把 .venv、基础分析库和平台的 dsflow 补齐。", *todo]
            commands = [env["fix"]]
        return {**base, "step": None, "phase": phase, "files": {}, "missing": [],
                "todo": todo, "commands": commands, "issues": [], "approvals": []}
    rev = current_revision(step)
    files = role_files(project, step, rev)
    phase, missing, todo, commands = _phase(step, files)
    if not env["ready"]:
        if phase == "plan" and _not_started(reg):
            phase, missing, todo, commands = "preflight", [], [
                f"分析环境还没准备好：{env['detail']}",
                "先调 env_check 看清楚缺哪一件，再调 env_prepare 把 .venv、基础分析库和平台的 dsflow 补齐。",
                "环境自检通过之后再写第一份计划；带着缺库的环境开始，执行 notebook 那一刻才报错，计划要重做。",
            ], [env["fix"]]
        elif phase in ("plan", "execute"):
            todo = [f"分析环境还没准备好：{env['detail']}先调 env_check 看清楚，再调 env_prepare 补齐，否则执行代码会报错。", *todo]
            commands = [env["fix"], *commands]
    return {
        **base,
        "step": {"id": step.id, "title": step.title, "status": step.status, "status_label": STATUS_LABEL[step.status],
                 "revision": rev.id, "dir": rev.dir},
        "phase": phase,
        "files": files,
        "missing": missing,
        "todo": todo,
        "commands": commands,
        "issues": [i.to_dict() for i in issues if i.step == step.id],
        "approvals": read_record(project, rev),
    }


PHASE_LABEL = {
    "preflight": "开工前检查环境", "plan": "写计划", "await_approval": "等用户审批", "execute": "执行并落盘", "acceptance": "主 agent 验收",
    "await_confirmation": "等用户确认", "next_step": "本步已结束", "all_done": "全部结束",
}
