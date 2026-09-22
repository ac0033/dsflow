"""审批闭环：用户在平台点「通过 / 退回 / 确认完成」，或主 agent 用 dsflow approve 记录对话里的原话。

这是平台唯一会改注册表（lifecycle/steps.json）的地方，所以集中在这里并加三道护栏：
只读项目一律拒绝；当前状态必须是转换的起点；写之前重新读文件、校验预检、临时文件加原子替换。
审批记录 approval_record.md 是给人看的追加式 Markdown，格式固定，parse_record 能解析回来。
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path

from .project import Project
from .schemas import STATUS_LABEL, Registry, Revision, Step
from .steps import revision_files, revisions_of
from .validate import ValidationIssue, parse_registry, validate_model

# (kind, decision) → (起点状态, 目标状态；None = 状态不变)
TRANSITIONS: dict[tuple[str, str], tuple[str, str | None]] = {
    ("approval", "approve"): ("pending_approval", "in_progress"),
    ("approval", "reject"): ("pending_approval", None),
    ("acceptance", "approve"): ("awaiting_acceptance", "done"),
    ("acceptance", "reject"): ("awaiting_acceptance", "in_progress"),
}
KIND_LABEL = {"approval": "计划审批", "acceptance": "完成确认"}
KIND_BY_STATUS = {"pending_approval": "approval", "awaiting_acceptance": "acceptance"}
DECISION_LABEL = {("approval", "approve"): "通过", ("approval", "reject"): "退回",
                  ("acceptance", "approve"): "确认", ("acceptance", "reject"): "退回"}
LABEL_TO_DECISION = {"通过": "approve", "确认": "approve", "退回": "reject", "撤回": "withdraw"}
LABEL_TO_KIND = {v: k for k, v in KIND_LABEL.items()}
WITHDRAW_LABEL = "撤回"
RECORD_NAME = "approval_record.md"
ENTRY = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · (通过|退回|确认|撤回) · (计划审批|完成确认)（(平台|命令行|MCP)）\s*$")
NOTE = re.compile(r"^\*\*原话\*\*：(.*)$")
STATE = re.compile(r"^- 状态：(\S+) → (\S+)\s*$")


class ApprovalError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def find_step(reg: Registry, step_id: str) -> Step:
    step = next((s for s in reg.steps if s.id == step_id), None)
    if step is None:
        raise ApprovalError(f"注册表里没有步骤 {step_id}", 404)
    return step


def current_revision(step: Step, rev_id: str | None = None) -> Revision:
    revs = revisions_of(step)
    wanted = rev_id or step.current_revision
    return next((r for r in revs if r.id == wanted), revs[-1])


def record_path(project: Project, rev: Revision) -> Path:
    return project.root / rev.dir / RECORD_NAME


def kind_for(step: Step) -> str:
    kind = KIND_BY_STATUS.get(step.status)
    if kind is None:
        raise ApprovalError(f"步骤 {step.id} 现在是「{STATUS_LABEL[step.status]}」，没有等待审批或确认的事", 409)
    return kind


# ---------- 记录文件 ----------


def parse_record(text: str) -> list[dict]:
    """把 approval_record.md 解析成条目列表（按文件顺序）。认不出的行忽略。"""
    entries: list[dict] = []
    for line in text.splitlines():
        m = ENTRY.match(line)
        if m:
            kind = LABEL_TO_KIND[m.group(3)]
            entries.append({"time": m.group(1), "decision": LABEL_TO_DECISION[m.group(2)], "decision_label": m.group(2),
                            "kind": kind, "kind_label": m.group(3), "source": m.group(4), "note": "", "from": None, "to": None})
            continue
        if not entries:
            continue
        m = NOTE.match(line)
        if m:
            entries[-1]["note"] = m.group(1).strip()
            continue
        m = STATE.match(line)
        if m:
            entries[-1]["from"], entries[-1]["to"] = m.group(1), m.group(2)
    return entries


def read_record(project: Project, rev: Revision) -> list[dict]:
    path = record_path(project, rev)
    return parse_record(path.read_text(encoding="utf-8")) if path.is_file() else []


def _basis(project: Project, step: Step, rev: Revision, kind: str) -> str:
    files, _ = revision_files(project.root, rev.dir, exclude_revisions=Path(rev.dir) == Path(step.dir))
    want = "plan" if kind == "approval" else "acceptance_report"
    hit = next((f for f in files if f["kind"] == want), None)
    if hit is None:
        return "plan.md 不存在" if kind == "approval" else "没有验收报告（用户仍确认完成）"
    stamp = datetime.fromtimestamp((project.root / hit["path"]).stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return f"{hit['rel']}（修改于 {stamp}）"


def _append_entry(project: Project, step: Step, rev: Revision, entry: dict) -> Path:
    path = record_path(project, rev)
    head = "" if path.is_file() else f"# 审批记录 · {step.id} {step.title}\n"
    body = (
        f"\n## {entry['time']} · {entry['decision_label']} · {entry['kind_label']}（{entry['source']}）\n"
        f"**原话**：{entry['note'] or '（没有留话）'}\n\n"
        f"- 状态：{entry['from']} → {entry['to']}\n"
        f"- 依据：{entry['basis']}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(head + body)
    return path


# ---------- 注册表写入 ----------


def _indent_of(text: str) -> int:
    m = re.search(r"\n( +)\"", text)
    return len(m.group(1)) if m else 2


def write_status(project: Project, step_id: str, rev_id: str, status: str) -> tuple[str, str]:
    """重新读注册表文件，只改这一步（和当前轮次）的 status，校验预检通过后原子替换。返回（旧状态, 新状态）。"""
    path = project.registry_path
    text = path.read_text(encoding="utf-8")
    raw = project.load_registry_raw()
    steps = raw.get("steps") or []
    target = next((s for s in steps if s.get("id") == step_id), None)
    if target is None:
        raise ApprovalError(f"注册表里没有步骤 {step_id}", 404)
    before = target.get("status")
    target["status"] = status
    for r in target.get("revisions") or []:
        if r.get("id") == rev_id:
            r["status"] = status
    reg, issues = parse_registry(raw)
    if reg is None:
        raise ApprovalError("改状态后注册表不再符合契约：" + "；".join(i.message for i in issues[:3]), 409)
    new_errors = [i for i in validate_model(reg, project.root) if i.severity == "error" and i.step == step_id]
    if new_errors:
        raise ApprovalError("改状态后本步校验不通过：" + "；".join(i.message for i in new_errors[:3]), 409)
    import json

    out = json.dumps(raw, ensure_ascii=False, indent=_indent_of(text))
    if text.endswith("\n"):
        out += "\n"
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(out, encoding="utf-8")
    os.replace(tmp, path)
    return before, status


def decide(project: Project, reg: Registry, step_id: str, kind: str, decision: str, note: str = "",
           source: str = "平台", rev_id: str | None = None) -> dict:
    """写一条审批 / 确认，并按转换表改注册表状态。"""
    if project.readonly:
        raise ApprovalError("只读接入的项目不在项目目录写任何文件；在对话里告诉 agent，让它用 dsflow approve 记录", 403)
    if (kind, decision) not in TRANSITIONS:
        raise ApprovalError(f"不认识的操作：{kind} / {decision}", 400)
    step = find_step(reg, step_id)
    rev = current_revision(step, rev_id)
    start, target = TRANSITIONS[(kind, decision)]
    if step.status != start:
        raise ApprovalError(
            f"步骤 {step_id} 现在是「{STATUS_LABEL[step.status]}」，{KIND_LABEL[kind]}要求它处于「{STATUS_LABEL[start]}」", 409)
    warnings: list[str] = []
    if kind == "approval" and decision == "approve" and not (project.root / rev.dir / "plan.md").is_file():
        raise ApprovalError(f"本轮目录 {rev.dir} 里没有 plan.md，没有计划就不能批准", 409)
    basis = _basis(project, step, rev, kind)
    if kind == "acceptance" and decision == "approve" and basis.startswith("没有验收报告"):
        warnings.append("这一步还没有验收报告；已按你的确认改为已完成，记录里注明了这一点")
    before = step.status
    after = target or step.status
    if target is not None:
        before, after = write_status(project, step_id, rev.id, target)
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "decision": decision,
        "decision_label": DECISION_LABEL[(kind, decision)], "kind": kind, "kind_label": KIND_LABEL[kind],
        "source": source, "note": (note or "").strip().replace("\n", " "), "from": before, "to": after, "basis": basis,
    }
    path = _append_entry(project, step, rev, entry)
    return {"step": step_id, "revision": rev.id, "kind": kind, "decision": decision, "from": before, "to": after,
            "record": path.relative_to(project.root).as_posix(), "entry": entry, "warnings": warnings}


def withdrawable(project: Project, step: Step, entries: list[dict]) -> tuple[bool, str]:
    """能不能撤回最后一条审批：不能的时候把原因说清楚，界面直接显示这句话。

    只让撤最后一条，且这一步的状态还停在那条记录留下的状态——已经接着往下做了就不再动它，
    否则撤回会把 agent 正在做的事从脚下抽走。记录本身永远不删，撤回也是追加一条。
    """
    if project.readonly:
        return False, "只读接入的项目不在项目目录写任何文件，撤回也不行；在对话里告诉 agent，让它用 dsflow withdraw 记录"
    if not entries:
        return False, "这一轮还没有审批记录，没有可撤回的"
    last = entries[-1]
    if last["decision"] == "withdraw":
        return False, "最后一条已经是撤回了"
    if last["to"] and step.status != last["to"]:
        return False, (f"这一步现在是「{STATUS_LABEL.get(step.status, step.status)}」，"
                       f"不是那条记录留下的「{STATUS_LABEL.get(last['to'], last['to'])}」："
                       "后面已经有别的改动，撤回会把正在做的事打断。要改就在对话里和 agent 说")
    return True, ""


def withdraw(project: Project, reg: Registry, step_id: str, note: str = "", source: str = "平台",
             rev_id: str | None = None) -> dict:
    """撤回最后一条审批：把状态改回那条记录之前的样子，并在记录里追加一条「撤回」。"""
    step = find_step(reg, step_id)
    rev = current_revision(step, rev_id)
    entries = read_record(project, rev)
    ok, why = withdrawable(project, step, entries)
    if not ok:
        raise ApprovalError(why, 403 if project.readonly else 409)
    last = entries[-1]
    before, after = step.status, last["from"] or step.status
    if after != before:
        before, after = write_status(project, step_id, rev.id, after)
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "decision": "withdraw", "decision_label": WITHDRAW_LABEL,
        "kind": last["kind"], "kind_label": last["kind_label"], "source": source,
        "note": (note or "").strip().replace("\n", " "), "from": before, "to": after,
        "basis": f"撤回 {last['time']} 的「{last['decision_label']} · {last['kind_label']}」",
    }
    path = _append_entry(project, step, rev, entry)
    return {"step": step_id, "revision": rev.id, "kind": last["kind"], "decision": "withdraw", "from": before,
            "to": after, "record": path.relative_to(project.root).as_posix(), "entry": entry,
            "withdrew": last, "warnings": []}


def approvals_view(project: Project, reg: Registry, step_id: str, rev_id: str | None = None) -> dict:
    step = find_step(reg, step_id)
    rev = current_revision(step, rev_id)
    path = record_path(project, rev)
    entries = read_record(project, rev)
    can_withdraw, why = withdrawable(project, step, entries)
    return {"step": step_id, "revision": rev.id, "status": step.status, "readonly": project.readonly,
            "pending": KIND_BY_STATUS.get(step.status),
            "path": path.relative_to(project.root).as_posix() if path.is_file() else None,
            "entries": entries, "can_withdraw": can_withdraw, "withdraw_blocked": "" if can_withdraw else why}


# ---------- agent 侧等待 ----------


def _status_of(project: Project, step_id: str) -> str | None:
    try:
        raw = project.load_registry_raw()
    except Exception:  # noqa: BLE001 — 文件正在被替换时读到一半，下一轮再读
        return None
    return next((s.get("status") for s in raw.get("steps") or [] if s.get("id") == step_id), None)


def wait_for(project: Project, step_id: str, kind: str = "any", timeout: float = 3600, interval: float = 2.0) -> dict:
    """阻塞到用户审批或确认为止：approved / confirmed / rejected / timeout。

    起点 =（当前状态, 记录条数）。记录里多了一条就按那条判；记录没变但状态变了也算（例如 agent 手工改的）。
    """
    reg, _ = project.load()
    if reg is None:
        raise ApprovalError("注册表无法解析", 409)
    step = find_step(reg, step_id)
    rev = current_revision(step)
    start_status = step.status
    start_count = len(read_record(project, rev))
    deadline = time.monotonic() + timeout
    while True:
        entries = read_record(project, rev)
        status = _status_of(project, step_id)
        # 最后一条是撤回，说明用户把刚才那条作废了：当作还没表态，继续等
        if len(entries) > start_count and entries[-1]["decision"] != "withdraw":
            last = entries[-1]
            if kind == "any" or last["kind"] == kind:
                result = "rejected" if last["decision"] == "reject" else ("confirmed" if last["kind"] == "acceptance" else "approved")
                return {"result": result, "step": step_id, "status": status, "entry": last}
        if status and status != start_status:
            # 平台先改状态、后追加记录：状态刚变时记录可能还没落盘，等一个间隔再读一次，别把上一条当成本次
            if len(entries) <= start_count:
                time.sleep(interval)
                entries = read_record(project, rev)
            result = {"in_progress": "approved", "done": "confirmed"}.get(status, "changed")
            return {"result": result, "step": step_id, "status": status, "entry": entries[-1] if entries else None}
        if time.monotonic() >= deadline:
            return {"result": "timeout", "step": step_id, "status": status, "entry": None}
        time.sleep(interval)


def issues_for(project: Project) -> list[ValidationIssue]:
    return project.load()[1]
