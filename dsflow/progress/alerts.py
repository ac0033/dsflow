"""自动告警：只报事实与可能的风险，严重程度从高到低：critical（原始数据被改）> serious > warning > info。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..core.project import Project
from ..core.schemas import MODEL_STATUS_LABEL, STATUS_LABEL, Registry
from ..core.steps import load_card, revision_files, revisions_of
from ..core.validate import ValidationIssue
from ..data.datasets import DatasetStore
from ..data.engine import DataError
from ..explain.guide import load_guide
from .checks import check_number

LEVELS = ("critical", "serious", "warning", "info")


def _latest(runs: list[dict], step: str, status: str | None = None) -> dict | None:
    return next((r for r in runs if r["step"] == step and (status is None or r["status"] == status)), None)


def _stale_detail(project: Project, rev_dir: str, card: dict | None) -> tuple[str, str]:
    """报告早于最新运行时，用说明卡上带出处的数字判断结果变没变。"""
    numbers = [n for n in (card or {}).get("core_numbers", []) if n.get("source")]
    if not numbers:
        return "warning", "，可能没有反映最新结果"
    results = [check_number(project, rev_dir, n) for n in numbers]
    bad = [r["label"] for r in results if r["status"] == "mismatch"]
    if bad:
        return "warning", f"；说明卡上 {len(bad)} 个数字与最新产物不一致（{'、'.join(bad[:3])}），报告需要更新"
    if all(r["status"] == "match" for r in results):
        return "info", f"；不过说明卡上 {len(results)} 个带出处的数字按最新产物重算全部一致"
    return "warning", "；说明卡上有数字无法按出处重算，可能没有反映最新结果"


def _describe_alerts(datasets: list[dict], add) -> None:
    """每份登记的数据都要有自己的一句介绍：数据里文件名下面那行小字就是它。

    空着，读的人只看得到行列数；几份数据共用同一句，等于谁也没介绍——两种都报出来。
    """
    written: dict[str, str] = {}
    for d in datasets:
        text = (d.get("description") or "").strip()
        path = d["versions"][-1]["path"]
        if not text:
            add("warning", "dataset_no_description",
                f"数据 {d['name']} 还没有写介绍：数据里它名字下面那行小字是空的。请写一句话说明它装的是什么、"
                f"怎么来的、后面哪一步会用。", link=path)
        elif text in written:
            add("warning", "dataset_same_description",
                f"数据 {d['name']} 和 {written[text]} 的介绍是同一句话：每份数据各写各的，读的人才分得清它们的差别。",
                link=path)
        else:
            written[text] = d["name"]


def compute_alerts(project: Project, reg: Registry, issues: list[ValidationIssue], runs: list[dict],
                   verify: bool = False) -> list[dict]:
    root = project.root
    out: list[dict] = []

    def add(level: str, code: str, message: str, step: str | None = None, link: str | None = None) -> None:
        out.append({"level": level, "code": code, "message": message, "step": step, "link": link})

    for issue in issues:
        if issue.severity == "error":
            add("serious", "registry", f"注册表校验未通过：{issue.message}", issue.step)

    # 原始数据只读：先比大小与修改时间（不算哈希，很快），verify=True 时再算哈希确认
    store = DatasetStore(project)
    datasets = store.list()
    _describe_alerts(datasets, add)
    for d in datasets:
        v = d["versions"][-1]
        if v["stage"] != "raw":
            continue
        try:
            known = store.cache.known_fingerprint(v["path"])
        except FileNotFoundError:
            add("critical", "raw_missing", f"原始数据 {d['name']}（{v['path']}）不见了：登记时的文件已不存在", link=v["path"])
            continue
        except DataError:
            continue
        if known == v["sha256"]:
            continue
        if known is None and verify:
            known = store.cache.fingerprint(v["path"])
            if known == v["sha256"]:
                continue
        if known is not None:
            add("critical", "raw_changed", f"原始数据 {d['name']}（{v['path']}）的内容与登记的版本 {v['version']} 不同。原始数据应当只读，请确认是谁、为什么改了它", link=v["path"])
        else:
            add("critical", "raw_maybe_changed", f"原始数据 {d['name']}（{v['path']}）的大小或修改时间与登记时不同，内容可能被改过（可以核对哈希确认）", link=v["path"])

    for step in reg.steps:
        sid = step.id
        revs = revisions_of(step)
        current = next((r for r in revs if r.id == step.current_revision), revs[-1])
        latest = _latest(runs, sid)
        if latest and latest["status"] == "failed":
            add("warning", "run_failed", f"步骤 {sid} 最近一次运行失败：{latest.get('error') or '没有记录原因'}", sid, f"runs/{latest['run_id']}")

        files = None
        ok = _latest(runs, sid, "succeeded")
        if ok:
            files, _ = revision_files(root, current.dir, exclude_revisions=Path(current.dir) == Path(step.dir))
            reports = [f for f in files if f["kind"] in ("report", "acceptance_report")]
            if reports:
                newest = max(reports, key=lambda f: (root / f["path"]).stat().st_mtime)
                written = datetime.fromtimestamp((root / newest["path"]).stat().st_mtime)
                started = datetime.fromisoformat(ok["started_at"])
                # 运行中写出的报告反映的就是这次运行，所以和运行开始时间比
                if written < started:
                    card, _ = load_card(root, current.dir)
                    level, tail = _stale_detail(project, current.dir, card)
                    add(level, "report_stale",
                        f"步骤 {sid} 的报告（{newest['rel']}，{written:%m-%d %H:%M}）写于最新一次成功运行开始（{started:%m-%d %H:%M}）之前{tail}",
                        sid, f"runs/{ok['run_id']}")

        # 轮次划分规则：新轮次必须在上一轮基础上递进（或从后面的阶段倒回来优化、试新方向）。
        # 覆盖式修改应更新原轮次而不是新增，所以 r02 起每一轮都要写明相对上一轮改了什么。
        for previous, rev in zip(revs, revs[1:]):
            if not (rev.summary or "").strip():
                add("warning", "revision_no_summary",
                    f"步骤 {sid} 的轮次 {rev.id} 没有写相对 {previous.id} 递进了什么。新轮次必须是递进或新方向；只是覆盖上一轮的内容，应更新 {previous.id} 而不是新增轮次",
                    sid)

        if step.status != "done":
            continue
        if step.revisions and current.status != "done":
            add("serious", "status_mismatch", f"步骤 {sid} 标为已完成，但当前轮次 {current.id} 是「{STATUS_LABEL[current.status]}」", sid)
        if files is None:
            files, _ = revision_files(root, current.dir, exclude_revisions=Path(current.dir) == Path(step.dir))
        if not step.acceptance_report and not any(f["kind"] == "acceptance_report" for f in files):
            add("warning", "no_acceptance", f"步骤 {sid} 标为已完成，但没有找到主验收报告（注册表没有登记，本轮目录也没有 acceptance.md 或 acceptance/*/report.md）", sid)
        guide, _, _, _ = load_guide(project, step, current)
        if guide is None:
            add("warning", "no_guide", f"步骤 {sid} 标为已完成，但本轮目录没有讲解 guide.yaml（用 dsflow guide init . {sid} 生成骨架）", sid, f"steps/{sid}?tab=guide")
        card, _ = load_card(root, current.dir)
        if card and card.get("can_continue") is False:
            add("serious", "card_blocks", f"步骤 {sid} 标为已完成，但说明卡写的是「暂不能继续」", sid)

    _model_alerts(project, add)
    return sorted(out, key=lambda a: LEVELS.index(a["level"]))


def _model_alerts(project: Project, add) -> None:
    """登记过的模型文件被覆盖或不见了；已交付的模型交付清单不齐全。"""
    from ..delivery.checklist import check_checklist
    from ..delivery.models import ModelStore

    store = ModelStore(project)
    for m in store.list():
        for v in m["versions"]:
            label = f"模型 {v['name']} 版本 {v['version']}（{MODEL_STATUS_LABEL[v['status']]}）"
            level = "warning" if v["status"] == "candidate" else "serious"
            link = f"models/{v['name']}/{v['version']}"
            state = store.quick_state(v)
            if state == "missing":
                add(level, "model_missing", f"{label}的文件 {v['path']} 不见了", v.get("step"), link)
            elif state == "maybe_changed" and not store.file_matches(v)[0]:
                add(level, "model_changed", f"{label}的文件内容与登记时不同。登记过的模型文件不应被覆盖：重新训练的结果请登记为新版本",
                    v.get("step"), link)
            if v["status"] == "delivered":
                c = check_checklist(project, v)
                if not c["complete"]:
                    add("warning", "checklist_incomplete", f"{label}已交付，但交付清单{c['summary']}", v.get("step"), link)
