"""注册表校验：lifecycle/steps.json 必须满足的全部规则。

规则失败以 ValidationIssue 返回而不抛异常，平台据此在流程图上标红。
本模块只检查文件是否存在、读取报告首行，不写任何文件。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import ValidationError

from .schemas import STATUS_LABEL, Registry

STEP_ID = re.compile(r"(\d+)\.(\d+)")
REPORT_NAMES = ("report.md", "user-report.md", "user-report.qmd", "user_report.md")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    step: str | None = None
    severity: str = "error"

    def to_dict(self) -> dict:
        return asdict(self)


def _inside(path: Path, base: Path) -> bool:
    return path.resolve().is_relative_to(base.resolve())


def parse_registry(raw: dict) -> tuple[Registry | None, list[ValidationIssue]]:
    try:
        return Registry.model_validate(raw), []
    except ValidationError as exc:
        issues = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            issues.append(ValidationIssue("schema", f"{loc}: {err['msg']}"))
        return None, issues


def validate_registry(raw: dict, root: Path) -> list[ValidationIssue]:
    reg, issues = parse_registry(raw)
    if reg is None:
        return issues
    return validate_model(reg, root)


def validate_model(reg: Registry, root: Path) -> list[ValidationIssue]:
    root = Path(root)
    stages = {s.id: s for s in reg.stages}
    steps = reg.steps
    issues: list[ValidationIssue] = []

    def err(code: str, message: str, step: str | None = None) -> None:
        issues.append(ValidationIssue(code, message, step))

    ids = [s.id for s in steps]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        err("duplicate_id", f"步骤编号存在重复：{'、'.join(duplicated)}")

    orders = sorted(s.order for s in steps)
    if orders != list(range(1, len(steps) + 1)):
        err("order_gap", f"order 必须从 1 连续编号，实际：{orders}")

    for s in steps:
        sid = s.id
        m = STEP_ID.fullmatch(sid)
        if not m:
            err("id_format", f"{sid}: 编号格式应为 阶段号.步号", sid)
            continue
        if int(m.group(1)) != s.stage:
            err("id_stage_mismatch", f"{sid}: 编号的阶段位与 stage 字段（{s.stage}）不一致", sid)
        stage = stages.get(s.stage)
        if stage is None:
            err("unknown_stage", f"{sid}: stage={s.stage} 未在 stages 中登记", sid)
            continue
        d = Path(s.dir)
        if d.parent.as_posix() != stage.dir:
            err("dir_outside_stage", f"{sid}: dir 不在阶段目录 {stage.dir} 下", sid)
        if not d.name.startswith(sid + "_"):
            err("dir_name", f"{sid}: 目录名 {d.name} 未以编号开头", sid)

        base = root / s.dir
        if s.acceptance_report:
            path = root / s.acceptance_report
            if not path.is_file() or not _inside(path, base):
                err("acceptance_report", f"{sid}: 主验收报告不存在或不属于本步骤: {s.acceptance_report}", sid)

        if s.status in ("done", "partial"):
            if not (base / "plan.md").exists():
                err("missing_file", f"{sid}: 缺少 {s.dir}/plan.md", sid)
            # 用户报告：平台默认 report.md；data-science-project skill 的默认名 user-report.md / .qmd 同样接受
            if not any((base / rel).exists() for rel in REPORT_NAMES):
                err("missing_file", f"{sid}: 缺少 {s.dir}/report.md（或 user-report.md / user-report.qmd）", sid)
            if s.execution_scripts:
                # DSFlow 扩展：用脚本执行时，登记的脚本代替 notebook（真实执行的证据是平台里的运行记录）
                for script in s.execution_scripts:
                    path = root / script
                    if not path.is_file() or not _inside(path, base):
                        err("script", f"{sid}: 执行脚本不存在或不属于该步骤: {script}", sid)
            else:
                notebooks = (
                    s.execution_notebooks if s.execution_notebooks is not None else [f"{s.dir}/nb_{sid}.ipynb"]
                )
                if not notebooks:
                    err("no_notebook", f"{sid}: 未登记真实执行notebook（用脚本执行时登记 execution_scripts）", sid)
                for notebook in notebooks:
                    path = root / notebook
                    if not path.is_file() or not _inside(path, base):
                        err("notebook", f"{sid}: notebook不存在或不属于该步骤: {notebook}", sid)
            report = base / "report.md"
            if report.exists():
                head = report.read_text(encoding="utf-8").lstrip()
                first = head.splitlines()[0] if head else ""
                if not first.startswith("#") or sid not in first:
                    err("report_heading", f"{sid}: report.md 首个标题未含编号", sid)
        elif s.status in ("in_progress", "awaiting_acceptance"):
            # DSFlow 扩展：执行必须有已批准的计划
            if not (base / "plan.md").exists():
                err("missing_file", f"{sid}: 状态为「{STATUS_LABEL[s.status]}」但缺少 {s.dir}/plan.md", sid)

        if s.revisions:
            revision_ids = [r.id for r in s.revisions]
            if len(revision_ids) != len(set(revision_ids)):
                err("duplicate_revision", f"{sid}: 轮次编号存在重复", sid)
            if s.current_revision not in revision_ids:
                err("current_revision", f"{sid}: current_revision={s.current_revision} 未在 revisions 中登记", sid)
            for revision in s.revisions:
                revision_dir = root / revision.dir
                if not revision_dir.exists():
                    err("revision_dir", f"{sid}/{revision.id}: 轮次目录不存在：{revision.dir}", sid)
                if not (revision_dir / "plan.md").exists():
                    err("revision_plan", f"{sid}/{revision.id}: 缺少 plan.md", sid)

    known = set(ids)
    for stage_id in stages:
        numbers = sorted(
            int(s.id.split(".")[1]) for s in steps if s.stage == stage_id and STEP_ID.fullmatch(s.id)
        )
        if numbers != list(range(1, len(numbers) + 1)):
            err("stage_numbering", f"阶段{stage_id}: 正式目的步骤编号不连续")

    if reg.dependencies is None:
        err("no_dependencies", "缺少显式 dependencies；禁止按编号自动推导依赖")
    for e in reg.dependencies or []:
        if e.from_ not in known or e.to not in known:
            err("dependency_ref", f"dependency 引用了不存在的步骤: {e.from_} → {e.to}")
    for e in reg.back_edges:
        for ref in (e.from_, e.to):
            if ref not in known:
                err("back_edge_ref", f"back_edges 引用了不存在的编号 {ref}")

    by_id = {s.id: s for s in steps}
    for e in reg.revision_loops:
        step = by_id.get(e.step)
        if step is None:
            err("revision_loop_ref", f"revision_loops 引用了不存在的编号 {e.step}")
            continue
        revision_ids = {r.id for r in step.revisions}
        for key, value in (("from_revision", e.from_revision), ("to_revision", e.to_revision)):
            if value not in revision_ids:
                err("revision_loop_ref", f"{e.step}: revision_loops 的 {key}={value} 未登记", e.step)

    # 分组：组 id 已登记；同组成员同阶段且 order 连续
    by_group: dict[str, list] = {}
    for s in steps:
        if not s.group:
            continue
        if s.group not in reg.groups:
            err("group_ref", f"{s.id}: 引用了未登记的组 {s.group}", s.id)
            continue
        by_group.setdefault(s.group, []).append(s)
    for gid, members in by_group.items():
        name = reg.groups[gid].name
        if len({m.stage for m in members}) != 1:
            err("group_stage", f"组 {gid}（{name}）成员跨阶段，不允许折叠")
        member_orders = sorted(m.order for m in members)
        if member_orders != list(range(member_orders[0], member_orders[0] + len(member_orders))):
            err("group_order", f"组 {gid}（{name}）成员执行顺序不连续：{member_orders}")

    return issues
