"""交付清单：delivery/<模型名>/checklist.yaml，放在项目里（文件是唯一事实来源）。

事实部分（模型版本、复现入口、训练数据版本、指标数值）由平台按模型登记与运行记录生成，`dsflow delivery init` 会刷新；
判断部分（一句话说明、使用入口、适用边界、监控方案、部署方式、遗留问题、指标口径与对照）由执行 agent 或负责人填写，刷新时保留。
平台核对：必填项齐全、没有「待填」、版本与登记一致、数据版本与指标数值与产出运行一致、产物文件都在。
"""

from __future__ import annotations

import yaml
from pydantic import ValidationError

from ..core.project import Project, ProjectError
from ..core.schemas import DeliveryChecklist
from ..progress.checks import parse_number
from ..tracking.store import reproduce

PLACEHOLDER = "待填"
HEADER = (
    "# 交付清单（DSFlow）。model / version / reproduce / data / metrics 的数值由平台按模型登记与运行记录生成，\n"
    "# `dsflow delivery init` 会刷新这些部分；其余由执行 agent 或负责人填写，刷新时保留。写着「待填」的地方都要填完。\n"
)


def checklist_rel(name: str) -> str:
    return f"delivery/{name}/checklist.yaml"


def load_checklist(project: Project, name: str) -> tuple[dict | None, str | None]:
    path = project.root / checklist_rel(name)
    if not path.is_file():
        return None, None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return DeliveryChecklist.model_validate(raw).model_dump(), None
    except (yaml.YAMLError, ValidationError) as exc:
        return None, "checklist.yaml 无法解析：" + " ".join(str(exc).split("\n")[:3])


def _holes(node, where: str = "") -> list[str]:
    """所有还写着「待填」的位置。"""
    if isinstance(node, str):
        return [where or "（根）"] if PLACEHOLDER in node else []
    if isinstance(node, dict):
        return [h for k, val in node.items() for h in _holes(val, f"{where}.{k}" if where else k)]
    if isinstance(node, list):
        return [h for i, val in enumerate(node) for h in _holes(val, f"{where}[{i}]")]
    return []


def _filled(s: str | None) -> bool:
    return bool(s and s.strip() and PLACEHOLDER not in s)


def _same_number(written, actual) -> bool:
    p = parse_number(written)
    if p is None or actual is None:
        return False
    value, dec = p
    return abs(round(actual, dec) - round(value, dec)) <= 10 ** (-dec) / 2 + 1e-9


def check_checklist(project: Project, v: dict) -> dict:
    """v 是 ModelStore.enrich 过的模型版本（带产出运行）。"""
    rel = checklist_rel(v["name"])
    c, error = load_checklist(project, v["name"])
    base = {"path": rel, "exists": (project.root / rel).is_file(), "error": error, "notes": [], "checklist": c}
    if c is None:
        summary = f"无法解析（{rel}）" if error else f"不存在（{rel}）"
        return {**base, "items": [], "passed": 0, "total": 0, "complete": False, "summary": summary}

    items: list[dict] = []

    def add(label: str, passed: bool, detail: str = "") -> None:
        items.append({"label": label, "passed": bool(passed), "detail": "" if passed else detail})

    run = v.get("run") or {}
    add("对应本模型版本", c["model"] == v["name"] and c["version"] == v["version"],
        f"清单写的是 {c['model']} {c['version']}，登记的是 {v['name']} {v['version']}")
    add("一句话说明", _filled(c["summary"]), "没写")
    add("复现入口", bool(c["reproduce"]), "没写（dsflow delivery init 会按运行记录生成）")
    add("使用入口", bool(c["usage"]) and all(_filled(u) for u in c["usage"]), "没写怎样用这个模型得到结果")

    listed = {(d["name"], d["version"]) for d in c["data"]}
    used = {(d["name"], d["version"]) for d in run.get("inputs") or []}
    add("训练数据版本与产出运行一致", bool(listed) and listed == used,
        f"清单：{'、'.join(f'{a} {b}' for a, b in sorted(listed)) or '无'}；运行：{'、'.join(f'{a} {b}' for a, b in sorted(used)) or '无'}")

    run_metrics = run.get("metrics") or {}
    bad = [m["name"] for m in c["metrics"] if m["name"] in run_metrics and not _same_number(m["value"], run_metrics[m["name"]])]
    unknown = [m["name"] for m in c["metrics"] if m["name"] not in run_metrics]
    add("指标数值与产出运行一致", bool(c["metrics"]) and not bad and not unknown,
        "没写指标" if not c["metrics"] else "；".join(filter(None, [
            f"与运行记录不同：{'、'.join(bad)}" if bad else "", f"运行里没有：{'、'.join(unknown)}" if unknown else ""])))
    add("指标口径", bool(c["metrics"]) and all(_filled(m["scope"]) for m in c["metrics"]),
        "每个指标都要写清在哪些数据上、按什么粒度算的")

    a = c["applicability"]
    add("适用范围", bool(a["scope"]) and all(_filled(x) for x in a["scope"]), "没写适用于什么")
    add("不适用的情况", bool(a["not_for"]) and all(_filled(x) for x in a["not_for"]), "没写不适用于什么")
    add("训练数据期间", _filled(a["data_period"]), "没写")
    add("监控方案", bool(c["monitoring"]) and all(_filled(m[k]) for m in c["monitoring"] for k in ("metric", "threshold", "frequency", "action")),
        "每一项都要写指标、阈值、频率和超过阈值后做什么")

    missing = []
    for art in c["artifacts"]:
        try:
            if not project.resolve(art["path"]).is_file():
                missing.append(art["path"])
        except ProjectError:
            missing.append(art["path"])
    add("产物文件都在", bool(c["artifacts"]) and not missing, f"缺：{'、'.join(missing)}" if missing else "没列产物")
    holes = _holes({k: val for k, val in c.items() if k not in ("reproduce",)})
    add("没有「待填」", not holes, f"还有 {len(holes)} 处：{'、'.join(holes[:6])}{' 等' if len(holes) > 6 else ''}")

    notes = []
    if c["deployment"].strip() in ("", "待定"):
        notes.append("部署方式待定")
    if c["open_items"]:
        notes.append(f"遗留问题 {len(c['open_items'])} 项")
    passed = sum(1 for i in items if i["passed"])
    failing = [i["label"] for i in items if not i["passed"]]
    summary = "齐全" if not failing else f"有 {len(failing)} 项未通过（{'、'.join(failing[:4])}{' 等' if len(failing) > 4 else ''}）"
    return {**base, "notes": notes, "items": items, "passed": passed, "total": len(items), "complete": not failing, "summary": summary}


def draft_checklist(project: Project, v: dict, existing: dict | None = None) -> dict:
    """事实部分按登记与运行记录重写；人写的部分沿用 existing，没有时放「待填」。"""
    run = v.get("run") or {}
    old = existing or {}
    commands = list(reproduce(run)["commands"]) if run else []
    commands.append(f'uv run dsflow data verify . "{v["path"]}" {v["sha256"]}    # 核对模型文件')
    old_metrics = {m["name"]: m for m in old.get("metrics", [])}
    metrics = [
        {"name": k, "value": val, "baseline": old_metrics.get(k, {}).get("baseline", ""),
         "scope": old_metrics.get(k, {}).get("scope") or f"{PLACEHOLDER}：在哪些数据上、按什么粒度算的"}
        for k, val in (run.get("metrics") or {}).items()
    ]
    applicability = old.get("applicability") or {}
    if not any(applicability.get(k) for k in ("scope", "not_for", "data_period", "known_weaknesses")):
        applicability = {"scope": [f"{PLACEHOLDER}：适用的对象、期间、粒度"], "not_for": [f"{PLACEHOLDER}：不适用的情况"],
                         "data_period": f"{PLACEHOLDER}：训练数据覆盖的期间", "known_weaknesses": []}
    artifacts = old.get("artifacts") or []
    if not any(a["path"] == v["path"] for a in artifacts):
        artifacts = [{"path": v["path"], "purpose": "模型文件", "kind": "model"}, *artifacts]
    out = {
        "model": v["name"],
        "version": v["version"],
        "summary": old.get("summary") or f"{PLACEHOLDER}：一句话说明交付什么、用来回答什么业务问题",
        "reproduce": commands,
        "usage": old.get("usage") or [f"{PLACEHOLDER}：怎样用这个模型得到结果（命令或调用方式）"],
        "data": [{k: d.get(k) for k in ("name", "version", "path", "sha256", "rows", "columns")} for d in run.get("inputs") or []],
        "metrics": metrics,
        "applicability": applicability,
        "monitoring": old.get("monitoring") or [{"metric": f"{PLACEHOLDER}：看什么指标", "threshold": f"{PLACEHOLDER}：到多少算异常",
                                                  "frequency": f"{PLACEHOLDER}：多久看一次", "action": f"{PLACEHOLDER}：超过阈值后做什么"}],
        "deployment": old.get("deployment") or "待定",
        "artifacts": artifacts,
        "open_items": old.get("open_items", []),
    }
    return DeliveryChecklist.model_validate(out).model_dump()


def write_checklist(project: Project, data: dict) -> str:
    if project.readonly:
        raise ProjectError("只读接入的项目不能由平台写入交付清单：请执行 agent 在项目里写 "
                           f"{checklist_rel(data['model'])}，或用 dsflow delivery init 在项目自己的环境里生成")
    rel = checklist_rel(data["model"])
    path = project.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    return rel
