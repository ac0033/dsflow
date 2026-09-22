"""DSFlow Agent Protocol：一套工具、三种传输（命令行 `dsflow call`、MCP `dsflow mcp`、HTTP `POST /api/tools/{name}`）。

任何 agent 接入平台都只用这里登记的工具；工具的名字、参数、返回结构在这里定义一次，
文档（`dsflow protocol`）、MCP 服务、HTTP 路由都从同一份登记表生成，不会各说各话。

约定：
- 每个工具都接受 `project`（平台里的项目 id，或项目目录路径）。
- 返回统一信封：成功 `{"ok": true, "protocol": "1", "data": …}`；失败 `{"ok": false, "protocol": "1", "error": {"code", "message", "hint"}}`。
  错误码：not_found / invalid / forbidden / readonly / conflict / io。
- 工具不替用户改状态：agent 只能把步骤改成「待审批」「待验收」，「进行中」「已完成」由用户在平台或对话里的审批产生。
"""

from __future__ import annotations

import inspect
import json
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .core.approval import ApprovalError, TRANSITIONS as APPROVAL_TRANSITIONS
from .core.project import Project, ProjectError
from .core.rules import WORK_RULES
from .core.schemas import STATUS_LABEL
from .index.db import PlatformIndex, open_for_write

PROTOCOL_VERSION = "1"

# ---------- 状态机与文件契约（协议文档和 next 都引用） ----------

STATES = ["pending", "pending_approval", "in_progress", "awaiting_acceptance", "done", "partial", "stopped"]
AGENT_TRANSITIONS = {("pending", "pending_approval"): "主 agent 写完 plan.md，提交审批",
                     ("in_progress", "awaiting_acceptance"): "执行 agent 落盘并通过 validate、check，提交验收"}
USER_TRANSITIONS = {(a, b or a): f"{k[1]} {k[0]}" for k, (a, b) in APPROVAL_TRANSITIONS.items()}
STEP_FILES = [
    {"file": "plan.md", "who": "主 agent", "when": "计划", "note": "为什么做、输入、处理办法、产物、验收标准、停止条件；写给用户评估"},
    {"file": "approval_record.md", "who": "平台 / approval_decide", "when": "审批与确认", "note": "不要手写；平台按固定格式追加"},
    {"file": "nb_<步骤>.ipynb", "who": "执行 agent", "when": "执行", "note": "真实执行的 notebook；公共代码放 src/；每次运行用 run_exec 记录"},
    {"file": "report.md", "who": "执行 agent 起草，主 agent 审阅", "when": "执行", "note": "用户报告：写给不看代码的读者，首个标题含步骤编号"},
    {"file": "step_card.yaml", "who": "执行 agent", "when": "执行", "note": "说明卡：headline / can_continue / core_numbers（带 source）/ artifacts（能出图就登记 figure）"},
    {"file": "guide.yaml", "who": "执行 agent 起草，主 agent 核对", "when": "执行", "note": "讲解：只讲 notebook 单元格；guide_put 会自动核对与体检"},
    {"file": "acceptance.md", "who": "主 agent", "when": "验收", "note": "从实际产物独立核对后写明为什么通过或未通过"},
]
PROTECTED = ("data/raw", "lifecycle/steps.json", "approval_record.md", ".dsflow", "dsflow.yaml")
REPORT_NAMES = {"report.md", "user-report.md", "user-report.qmd", "user_report.md"}


# ---------- 登记表 ----------


@dataclass
class ToolSpec:
    name: str
    description: str
    group: str
    returns: str
    fn: Callable[..., Any]
    params: dict = field(default_factory=dict)  # 参数名 → 一句说明（类型与默认值从函数签名取）

    def schema(self) -> dict:
        sig = inspect.signature(self.fn)
        props, required = {}, []
        for pname, p in sig.parameters.items():
            ann = p.annotation
            t = {"str": "string", "int": "integer", "float": "number", "bool": "boolean", "list": "array", "dict": "object"}
            base = str(ann).replace("typing.", "").replace(" | None", "").replace("list[str]", "list").replace("dict[str, str]", "dict")
            entry: dict = {"type": t.get(base, "string"), "description": self.params.get(pname, "")}
            if p.default is inspect.Parameter.empty:
                required.append(pname)
            else:
                entry["default"] = p.default
            props[pname] = entry
        return {"type": "object", "properties": props, "required": required}

    def describe(self) -> dict:
        return {"name": self.name, "group": self.group, "description": self.description, "params": self.schema(), "returns": self.returns}


REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, group: str, description: str, returns: str, /, **params: str):
    """前四个是位置参数（`/`），这样 `name=`、`path=` 这类参数说明能作为关键字传进 params。"""
    def deco(fn):
        REGISTRY[name] = ToolSpec(name, description, group, returns, fn, params)
        return fn
    return deco


class ToolError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code, self.hint = code, hint


def envelope_ok(data: Any) -> dict:
    return {"ok": True, "protocol": PROTOCOL_VERSION, "data": data}


def envelope_error(code: str, message: str, hint: str = "") -> dict:
    return {"ok": False, "protocol": PROTOCOL_VERSION, "error": {"code": code, "message": message, "hint": hint}}


_ERROR_CODES = {ApprovalError: lambda e: {403: "readonly", 404: "not_found", 400: "invalid"}.get(e.status, "conflict"),
                ProjectError: lambda e: "invalid", FileNotFoundError: lambda e: "not_found", KeyError: lambda e: "not_found",
                PermissionError: lambda e: "forbidden", OSError: lambda e: "io", ValueError: lambda e: "invalid"}


def call(name: str, args: dict | None = None) -> dict:
    """按名字调用一个工具，永远返回信封（不抛异常）。三种传输都走这里。"""
    spec = REGISTRY.get(name)
    if spec is None:
        return envelope_error("not_found", f"没有这个工具：{name}", "用 protocol_get 看全部工具")
    args = dict(args or {})
    sig = inspect.signature(spec.fn)
    unknown = [k for k in args if k not in sig.parameters]
    if unknown:
        return envelope_error("invalid", f"{name} 不认识参数：{'、'.join(unknown)}", f"可用参数：{'、'.join(sig.parameters)}")
    missing = [k for k, p in sig.parameters.items() if p.default is inspect.Parameter.empty and k not in args]
    if missing:
        return envelope_error("invalid", f"{name} 缺少参数：{'、'.join(missing)}")
    try:
        return envelope_ok(spec.fn(**args))
    except ToolError as exc:
        return envelope_error(exc.code, str(exc), exc.hint)
    except tuple(_ERROR_CODES) as exc:  # noqa: PERF203
        code = next(c(exc) for t, c in _ERROR_CODES.items() if isinstance(exc, t))
        return envelope_error(code, str(exc) or type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 — 工具内部错误也要以信封返回，agent 才能读懂
        return envelope_error("io", f"{type(exc).__name__}: {exc}")


def protocol_document() -> dict:
    return {
        "protocol": PROTOCOL_VERSION,
        "transports": {
            "cli": "dsflow call <tool> --args '<json>'（任何有 shell 的 agent）",
            "mcp": "dsflow mcp（stdio）或平台的 /mcp（streamable HTTP）",
            "http": "POST /api/tools/<tool>，body 就是参数 JSON；GET /api/protocol 是本文档",
        },
        "envelope": {"ok": {"ok": True, "protocol": PROTOCOL_VERSION, "data": "…"},
                     "error": {"ok": False, "protocol": PROTOCOL_VERSION, "error": {"code": "not_found|invalid|forbidden|readonly|conflict|io", "message": "…", "hint": "…"}}},
        "states": [{"id": s, "label": STATUS_LABEL[s]} for s in STATES],
        "transitions": {
            "agent": [{"from": a, "to": b, "when": w} for (a, b), w in AGENT_TRANSITIONS.items()],
            "user": [{"from": a, "to": b, "via": w} for (a, b), w in USER_TRANSITIONS.items()],
        },
        "files": STEP_FILES,
        "rules": WORK_RULES,
        "loop": ["接入后第一次：env_check（环境不齐就 env_prepare），确认分析环境建好了再开始",
                 "next", "写 plan.md（file_write）→ step_set_status pending_approval → approval_wait",
                 "执行：run_exec / data_register / file_write（report.md、step_card.yaml）/ guide_put → validate、check → step_set_status awaiting_acceptance",
                 "验收：file_write acceptance.md、guide_check、guide_lint → approval_wait", "用户确认后 next 进入下一步"],
        "tools": [spec.describe() for spec in REGISTRY.values()],
    }


# ---------- 公共辅助 ----------

_HEX10 = re.compile(r"^[0-9a-f]{10}$")


def _project(project: str) -> Project:
    """平台 id 或目录路径都行；已登记的沿用登记的读写模式，未登记的目录视为可写。"""
    if _HEX10.match(project or ""):
        try:
            return PlatformIndex().open_project(project)
        except KeyError:
            raise ToolError("not_found", f"平台里没有 id 为 {project} 的项目", "用 projects_list 看已登记项目，或直接传项目目录路径") from None
    path = Path(project)
    if not path.is_dir():
        raise ToolError("not_found", f"项目目录不存在：{project}")
    return open_for_write(path)


def _loaded(project: str):
    p = _project(project)
    reg, issues = p.load()
    if reg is None:
        raise ToolError("invalid", "注册表无法解析：" + "；".join(i.message for i in issues[:3]), "先修 lifecycle/steps.json")
    return p, reg, issues


def _writable(p: Project) -> None:
    if p.readonly:
        raise ToolError("readonly", "这个项目登记为只读接入，平台不在它的目录里写文件", "用 dsflow attach --force 改成可写")


def _rel(p: Project, path: str) -> str:
    full = (p.root / path).resolve()
    if not full.is_relative_to(p.root):
        raise ToolError("forbidden", "路径越出项目目录")
    return full.relative_to(p.root).as_posix()


def _current_dirs(reg) -> dict[str, str]:
    from .core.approval import current_revision

    return {s.id: current_revision(s).dir for s in reg.steps}


# ---------- 工具：项目与进度 ----------


@tool("protocol_get", "协议", "本协议的机器可读版：状态机、文件契约、全部工具及参数。", "协议文档")
def protocol_get() -> dict:
    return protocol_document()


@tool("projects_list", "项目", "平台里登记的项目。", "[{id, name, root, readonly, step_count}]")
def projects_list() -> list[dict]:
    return [{k: r[k] for k in ("id", "name", "root", "readonly", "step_count") if k in r} for r in PlatformIndex().list_projects()]


# ---------- 工具：环境 ----------


@tool("env_check", "环境", "开工前的环境自检：项目有没有自己的 .venv、平台的 dsflow 挂没挂进去、要用的库能不能真的 import 进来。"
      "接入之后、写第一份计划之前先调它；ready 为 false 就先修环境再开始，不要带着报错执行。",
      "{ready, python, checks: [{name, status, detail, fix}], fix}",
      project="项目 id 或目录", imports="基础分析库以外还要确认能 import 的库名（计划里要用什么就写什么）")
def env_check(project: str, imports: list[str] | None = None) -> dict:
    from .env import check

    return check(_project(project).root, imports)


@tool("env_prepare", "环境", "准备分析环境：在项目里建 .venv、装基础分析库（pandas、matplotlib、scikit-learn、openpyxl）、把平台的 dsflow 挂进去，"
      "装完再自检一遍。第一次要联网下载，可能要几分钟；只读接入的项目不做。",
      "{ready, log, checks}", project="项目 id 或目录", libs="除基础分析库以外还要装的库名")
def env_prepare(project: str, libs: list[str] | None = None) -> dict:
    from .env import DEFAULT_LIBS, EnvError, check, prepare

    p = _project(project)
    _writable(p)
    try:
        log = list(prepare(p.root, libs=tuple(DEFAULT_LIBS) + tuple(libs or ())))
    except EnvError as exc:
        raise ToolError("io", str(exc), "在项目目录里运行 dsflow attach . --venv 看完整输出") from None
    out = check(p.root, libs)
    return {"ready": out["ready"], "log": log, "checks": out["checks"], "fix": out["fix"]}


@tool("next", "进度", "项目在哪一步、处于哪个环节、本轮目录缺什么文件、该做什么；tool_calls 是下一步该调的工具。"
      "environment 是分析环境的快检查，rules 是每个环节都要守的工作规矩。",
      "{step, phase, files, missing, todo, commands, tool_calls, issues, attention, approvals, environment, rules}",
      project="项目 id 或目录", step="只看某一步（默认取顺序最靠前的进行中步骤）")
def next_step(project: str, step: str | None = None) -> dict:
    from .core.next import next_action

    p, reg, issues = _loaded(project)
    out = next_action(p, reg, issues, step)
    out["protocol"] = PROTOCOL_VERSION
    out["tool_calls"] = _tool_calls(p, out)
    return out


def _tool_calls(p: Project, nxt: dict) -> list[dict]:
    s = nxt.get("step")
    env_ready = (nxt.get("environment") or {}).get("ready", True)
    env_calls = [] if env_ready else [{"tool": "env_check", "args": {"project": p.id}},
                                      {"tool": "env_prepare", "args": {"project": p.id}}]
    if not s:
        first = env_calls if nxt["phase"] == "preflight" else []
        return first + [{"tool": "step_add", "args": {"project": p.id, "step": "<编号，如 1.1>", "stage": 1, "title": "<标题>", "op": "<这一步的目的>"}}]
    pid, sid, d = p.id, s["id"], s["dir"]
    phase = nxt["phase"]
    if phase == "preflight":
        return env_calls + [{"tool": "next", "args": {"project": pid}}]
    if phase == "plan":
        return env_calls + [{"tool": "file_write", "args": {"project": pid, "path": f"{d}/plan.md", "content": "<计划正文>"}},
                {"tool": "step_set_status", "args": {"project": pid, "step": sid, "status": "pending_approval"}},
                {"tool": "approval_wait", "args": {"project": pid, "step": sid}}]
    if phase == "await_approval":
        return [{"tool": "approval_wait", "args": {"project": pid, "step": sid}}]
    if phase == "execute":
        return env_calls + [{"tool": "run_exec", "args": {"project": pid, "step": sid, "target": f"{d}/nb_{sid}.ipynb", "hypothesis": "<这次要验证什么>"}},
                {"tool": "file_write", "args": {"project": pid, "path": f"{d}/report.md", "content": "<用户报告>"}},
                {"tool": "file_write", "args": {"project": pid, "path": f"{d}/step_card.yaml", "content": "<说明卡>"}},
                {"tool": "guide_init", "args": {"project": pid, "step": sid}},
                {"tool": "guide_put", "args": {"project": pid, "step": sid, "text": "<填好的 guide.yaml>"}},
                {"tool": "validate", "args": {"project": pid}}, {"tool": "check", "args": {"project": pid, "step": sid}},
                {"tool": "step_set_status", "args": {"project": pid, "step": sid, "status": "awaiting_acceptance"}}]
    if phase == "acceptance":
        return [{"tool": "guide_check", "args": {"project": pid, "step": sid}}, {"tool": "guide_lint", "args": {"project": pid, "step": sid}},
                {"tool": "file_write", "args": {"project": pid, "path": f"{d}/acceptance.md", "content": "<验收报告>"}},
                {"tool": "approval_wait", "args": {"project": pid, "step": sid}}]
    if phase == "await_confirmation":
        return [{"tool": "approval_wait", "args": {"project": pid, "step": sid}}]
    return [{"tool": "next", "args": {"project": pid}}]


@tool("steps_list", "进度", "全部步骤：编号、标题、阶段、状态、当前轮次、目录。", "[{id, title, stage, order, status, status_label, revision, dir}]", project="项目 id 或目录")
def steps_list(project: str) -> list[dict]:
    _, reg, _ = _loaded(project)
    return [{"id": s.id, "title": s.title, "stage": s.stage, "order": s.order, "status": s.status,
             "status_label": STATUS_LABEL[s.status], "revision": s.current_revision or "r01", "dir": s.dir} for s in reg.steps]


@tool("step_add", "进度", "在注册表里登记一个新步骤（状态 pending）：编号、阶段、标题、目录（默认 steps/<阶段目录>/<编号>_<标题>）、依赖的步骤。新项目提出阶段划分后用它把步骤一个个登记进来。"
      "一步是一个完整独立的单元：有自己的输入、产物和能核对的验收标准；不要把一个阶段的操作堆成一步，也不要把一个操作拆成三步。",
      "{id, dir, stage}", project="项目 id 或目录", step="步骤编号，如 1.1", stage="阶段序号（见 dsflow.yaml / 注册表 stages）", title="标题",
      dir="目录（相对项目根，可省略）", depends_on="依赖的步骤编号（显式登记，不按编号推导）", op="这一步的目的（一句话）")
def step_add(project: str, step: str, stage: int, title: str, dir: str | None = None, depends_on: list[str] | None = None, op: str = "") -> dict:
    import os

    from .core.validate import parse_registry, validate_model

    p = _project(project)
    _writable(p)
    path = p.registry_path
    raw = p.load_registry_raw()
    if any(s.get("id") == step for s in raw.get("steps") or []):
        raise ToolError("conflict", f"步骤 {step} 已经登记过", "用 steps_list 看现有步骤")
    stage_row = next((s for s in raw.get("stages") or [] if s.get("id") == stage), None)
    if stage_row is None:
        raise ToolError("invalid", f"没有阶段 {stage}", "阶段序号见 steps_list 或注册表 stages")
    known = {s.get("id") for s in raw.get("steps") or []}
    unknown = [d for d in (depends_on or []) if d not in known]
    if unknown:
        raise ToolError("invalid", f"依赖的步骤不存在：{'、'.join(unknown)}", "先登记被依赖的步骤")
    rel = dir or f"{stage_row['dir']}/{step}_{title}"
    order = max((s.get("order", 0) for s in raw.get("steps") or []), default=0) + 1
    raw.setdefault("steps", []).append({"id": step, "stage": stage, "order": order, "title": title, "dir": rel, "status": "pending",
                                        "op": op, "finding": "", "decision": ""})
    deps = raw.get("dependencies")
    if deps is None:
        deps = raw["dependencies"] = []
    for d in depends_on or []:
        deps.append({"from": d, "to": step, "label": ""})
    reg, issues = parse_registry(raw)
    if reg is None:
        raise ToolError("invalid", "登记后注册表不符合契约：" + "；".join(i.message for i in issues[:3]))
    errors = [i for i in validate_model(reg, p.root) if i.severity == "error" and i.step == step]
    if errors:
        raise ToolError("invalid", "登记后本步校验不通过：" + "；".join(i.message for i in errors[:3]))
    text = path.read_text(encoding="utf-8")
    from .core.approval import _indent_of

    out = json.dumps(raw, ensure_ascii=False, indent=_indent_of(text)) + ("\n" if text.endswith("\n") else "")
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(out, encoding="utf-8")
    os.replace(tmp, path)
    (p.root / rel).mkdir(parents=True, exist_ok=True)
    return {"id": step, "dir": rel, "stage": stage, "order": order}


@tool("step_get", "进度", "一步的详情：轮次、本轮文件（按角色）、说明卡、验收报告、依赖。", "step_detail",
      project="项目 id 或目录", step="步骤编号")
def step_get(project: str, step: str) -> dict:
    from .core.steps import step_detail

    p, reg, issues = _loaded(project)
    d = step_detail(p.root, reg, step, issues)
    for r in d["revisions"]:
        r["files"] = [{"path": f["path"], "rel": f["rel"], "kind": f["kind"], "size": f["size"]} for f in r["files"]]
    return d


# ---------- 工具：文件 ----------


@tool("file_read", "文件", "读项目里的一个文本文件（相对项目根目录）。", "{path, size, suffix, content}", project="项目 id 或目录", path="相对路径")
def file_read(project: str, path: str) -> dict:
    return _project(project).read_text(path)


@tool("file_write", "文件", "写项目里的文件。只允许写当前轮次目录（及项目根目录的 src/）；不能写 data/raw、注册表、审批记录、历史轮次。写 guide.yaml 会顺带体检。",
      "{path, bytes, lint?}", project="项目 id 或目录", path="相对路径", content="全文", append="true 时追加而不是覆盖")
def file_write(project: str, path: str, content: str, append: bool = False) -> dict:
    p, reg, _ = _loaded(project)
    _writable(p)
    rel = _rel(p, path)
    if any(rel == x or rel.startswith(x + "/") for x in PROTECTED) or rel.endswith("/approval_record.md"):
        raise ToolError("forbidden", f"不能写 {rel}", "原始数据只读；状态用 step_set_status；审批记录由 approval_decide 写")
    allowed = [d for d in _current_dirs(reg).values()]
    if not (rel.startswith("src/") or any(rel == d or rel.startswith(d + "/") for d in allowed)):
        raise ToolError("forbidden", f"{rel} 不在任何步骤的当前轮次目录里", "历史轮次不改；返工请开新轮次；本轮目录见 steps_list 的 dir")
    if "/revisions/" in rel and not any(rel.startswith(d + "/") for d in allowed if "/revisions/" in d):
        raise ToolError("forbidden", f"{rel} 属于历史轮次", "历史轮次不覆盖")
    full = p.root / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    with full.open("a" if append else "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    out = {"path": rel, "bytes": full.stat().st_size}
    if full.name == "guide.yaml":
        out["lint"] = guide_lint(project, _step_of(reg, rel))
    return out


def _step_of(reg, rel: str) -> str | None:
    for sid, d in _current_dirs(reg).items():
        if rel.startswith(d + "/"):
            return sid
    return None


# ---------- 工具：状态 ----------


@tool("step_set_status", "状态", "agent 能做的两种状态变化：pending → pending_approval（提交审批）、in_progress → awaiting_acceptance（提交验收）。其余由用户审批产生。",
      "{step, from, to}", project="项目 id 或目录", step="步骤编号", status="pending_approval 或 awaiting_acceptance")
def step_set_status(project: str, step: str, status: str) -> dict:
    from .core.approval import current_revision, find_step, write_status

    p, reg, _ = _loaded(project)
    _writable(p)
    s = find_step(reg, step)
    if (s.status, status) not in AGENT_TRANSITIONS:
        allowed = "、".join(f"{a} → {b}" for a, b in AGENT_TRANSITIONS)
        raise ToolError("conflict", f"步骤 {step} 现在是「{STATUS_LABEL[s.status]}」，不能由 agent 改成 {status}", f"agent 只能做：{allowed}；通过 / 退回 / 确认由用户审批产生")
    before, after = write_status(p, step, current_revision(s).id, status)
    return {"step": step, "from": before, "to": after}


# ---------- 工具：运行 ----------


def _python_for(p: Project) -> list[str]:
    for cand in (".venv/Scripts/python.exe", ".venv/bin/python"):
        if (p.root / cand).is_file():
            return [str(p.root / cand)]
    if (p.root / "pyproject.toml").is_file():
        return ["uv", "run", "python"]
    return [sys.executable]


@tool("run_exec", "运行", "在平台所在机器上执行项目内的 notebook（走 dsflow 的 notebook 执行器）或脚本，并记录为一次运行。只能执行项目目录内的文件。超时未结束就返回 running，用 run_get 追踪。",
      "{run_id, status, exit_code, duration_s, log_tail}", project="项目 id 或目录", step="步骤编号", target="notebook 或脚本的相对路径",
      hypothesis="这次运行要验证什么", params="notebook 参数（名 → 值）", timeout="最多等多少秒（默认 600）")
def run_exec(project: str, step: str, target: str, hypothesis: str = "", params: dict[str, str] | None = None, timeout: int = 600) -> dict:
    from .tracking.runner import execute, prepare
    from .tracking.store import RunStore

    p, reg, _ = _loaded(project)
    _writable(p)
    rel = _rel(p, target)
    if not (p.root / rel).is_file():
        raise ToolError("not_found", f"文件不存在：{rel}")
    if rel.startswith("data/raw"):
        raise ToolError("forbidden", "原始数据目录里的文件不能执行")
    py = _python_for(p)
    if rel.endswith(".ipynb"):
        argv = [*py, "-m", "dsflow.tracking.notebook", rel] + [x for k, v in (params or {}).items() for x in ("--param", f"{k}={v}")]
    elif rel.endswith(".py"):
        argv = [*py, rel]
    else:
        raise ToolError("invalid", "只能执行 .ipynb 或 .py", "其他命令请在本机用 dsflow run")
    run = prepare(p, step, argv, hypothesis=hypothesis, source="tool")
    result: dict = {}
    th = threading.Thread(target=lambda: result.update(execute(p, run["run_id"])), daemon=True)
    th.start()
    th.join(timeout)
    store = RunStore(p)
    current = store.get(run["run_id"]) or run
    return _run_view(store, current if th.is_alive() else (result or current))


def _run_view(store, run: dict) -> dict:
    log = store.log_path(run["run_id"])
    tail = ""
    if log.is_file():
        text = log.read_text(encoding="utf-8", errors="replace")
        tail = text[-4000:]
    return {"run_id": run["run_id"], "status": run.get("status"), "exit_code": run.get("exit_code"),
            "duration_s": run.get("duration_s"), "error": run.get("error"), "conclusion": run.get("conclusion"),
            "validity": run.get("validity"), "metrics": run.get("metrics"), "log_tail": tail}


@tool("run_get", "运行", "一次运行的状态、指标、结论和日志尾部。", "{run_id, status, …, log_tail}", project="项目 id 或目录", run_id="运行编号")
def run_get(project: str, run_id: str) -> dict:
    from .tracking.store import RunStore

    store = RunStore(_project(project))
    run = store.get(run_id)
    if run is None:
        raise ToolError("not_found", f"没有运行 {run_id}")
    return _run_view(store, run)


@tool("runs_list", "运行", "最近的运行记录。", "[{run_id, step, status, started_at, hypothesis, conclusion, validity}]", project="项目 id 或目录", step="只看某一步", limit="最多几条")
def runs_list(project: str, step: str | None = None, limit: int = 20) -> list[dict]:
    from .tracking.store import RunStore

    runs = RunStore(_project(project)).list(step)[:limit]
    return [{k: r.get(k) for k in ("run_id", "step", "status", "started_at", "hypothesis", "conclusion", "validity", "exit_code")} for r in runs]


# ---------- 工具：数据与模型 ----------


@tool("data_register", "数据", "登记一个数据集版本（只记路径与哈希）。产出的表写清上游、产出步骤；替代旧表就写 replaces。",
      "{version, created}", project="项目 id 或目录", path="文件相对路径", name="数据集名（用数据表里的说法）",
      stage="raw / processed / features / splits / model_input / predictions / other", parents="上游数据集名",
      produced_by="产出它的步骤", description="一句话介绍这份数据：一行代表什么、怎么来的、后面哪一步会用；每份数据各写各的",
      replaces="它登记后不再有用的数据集名")
def data_register(project: str, path: str, name: str, stage: str = "raw", parents: list[str] | None = None,
                  produced_by: str | None = None, description: str = "", replaces: list[str] | None = None) -> dict:
    from .data.datasets import DatasetStore

    p = _project(project)
    out = DatasetStore(p).register(path, name, stage, parents or [], produced_by, description, replaces or [])
    return {"version": out["version"], "created": out["created"]}


@tool("data_describe", "数据", "补写或改写一份数据的介绍（数据里文件名下面那行小字），不必重新登记。", "{name, description}",
      project="项目 id 或目录", name="数据集名",
      description="一句话介绍这份数据：一行代表什么、怎么来的、后面哪一步会用；每份数据各写各的")
def data_describe(project: str, name: str, description: str) -> dict:
    from .data.datasets import DatasetStore

    data = DatasetStore(_project(project)).describe(name, description)
    return {"name": name, "description": data["description"]}


@tool("data_link", "数据", "把一张只读没改的表挂到某一步（核对 / 读取），数据层才能显示这一步碰了它。", "{name, step, role}",
      project="项目 id 或目录", name="数据集名", step="步骤编号", role="核对 或 读取")
def data_link(project: str, name: str, step: str, role: str = "读取") -> dict:
    from .data.datasets import DatasetStore

    DatasetStore(_project(project)).link(name, step, role)
    return {"name": name, "step": step, "role": role}


@tool("data_replace", "数据", "声明替代关系：新表登记后旧表退出「后存量」。", "{name, replaces}", project="项目 id 或目录", name="新表名", old="被替代的表名")
def data_replace(project: str, name: str, old: list[str]) -> dict:
    from .data.datasets import DatasetStore

    DatasetStore(_project(project)).set_replaces(name, old)
    return {"name": name, "replaces": old}


@tool("data_list", "数据", "数据集演变链：每个数据集的版本、产出步骤、替代关系。", "[dataset]", project="项目 id 或目录")
def data_list(project: str) -> list[dict]:
    from .data.datasets import DatasetStore

    return DatasetStore(_project(project)).list()


@tool("data_peek", "数据", "看一份数据文件的前几行（最多 20 行、8 列），并给出这张表的全部列名。只读前几行，不整表转换，大文件也很快。",
      "{path, format, columns, rows, all_columns, total_columns, size}", project="项目 id 或目录", path="数据文件相对路径",
      columns="只看这几列（逗号分隔；留空取前 8 列）", limit="看几行（最多 20）", sheet="xlsx 的第几个工作表（从 0 数）")
def data_peek(project: str, path: str, columns: str = "", limit: int = 5, sheet: int = 0) -> dict:
    from .data.peek import peek

    return peek(_project(project), path, [c.strip() for c in columns.split(",") if c.strip()], limit, sheet)


@tool("data_query", "数据", "对一份数据文件跑一条只读 SQL：数一数、分组汇总、挑几行来看。表名固定写 data，"
      "只能 SELECT / WITH（不能改任何东西）。文件要先转成 Parquet（在网页的数据页打开过一次就有），没转的先用 data_peek。",
      "{columns, rows, truncated}", project="项目 id 或目录", path="数据文件相对路径",
      sql="一条查询语句，表名写 data，例如 SELECT 类目, count(*) AS 行数 FROM data GROUP BY 1 ORDER BY 2 DESC",
      limit="最多返回多少行（默认 50，上限 200）")
def data_query(project: str, path: str, sql: str, limit: int = 50) -> dict:
    from .data.browse import run_sql
    from .data.cache import DataCache
    from .data.engine import DataError, QueryError

    p = _project(project)
    try:
        parquet = DataCache(p).parquet_if_ready(path)
    except FileNotFoundError:
        raise ToolError("not_found", f"项目里没有这个文件：{path}", "路径相对项目根目录；data_list 能看到登记过的表") from None
    except DataError as exc:
        raise ToolError("bad_request", str(exc), "支持 csv / tsv / xlsx / parquet") from None
    if parquet is None:
        raise ToolError("not_ready", f"{path} 还没转换成 Parquet，现在查不了",
                        "先用 data_peek 看前几行；要整表查询，让用户在网页的数据页打开这张表一次（转换会缓存下来）")
    try:
        return run_sql(parquet, sql, limit=min(max(int(limit), 1), 200))
    except QueryError as exc:
        raise ToolError("bad_request", str(exc), "只允许一条 SELECT / WITH 语句，表名写 data") from None


@tool("model_register", "模型", "登记模型文件为候选版本（不覆盖已登记的文件）。", "{name, version}", project="项目 id 或目录",
      path="模型文件相对路径", name="模型名", run_id="产出它的运行编号", description="一句话说明")
def model_register(project: str, path: str, name: str, run_id: str | None = None, description: str = "") -> dict:
    from .delivery.models import ModelStore

    out = ModelStore(_project(project)).register(path, name, run_id, description)
    return {"name": name, "version": out.get("version"), "status": out.get("status")}


# ---------- 工具：讲解 ----------


def _guide_ctx(project: str, step: str, rev: str | None):
    from .explain.guide import find_step, pick_revision

    p, reg, _ = _loaded(project)
    s = find_step(reg, step)
    return p, reg, s, pick_revision(s, rev)


@tool("guide_init", "讲解", "按 notebook 真实单元格生成 guide.yaml 骨架并写到本轮目录（已有就不覆盖，返回现有内容）。", "{path, text, existed}",
      project="项目 id 或目录", step="步骤编号", rev="轮次", notebook="本轮有多个 notebook 时指定一个")
def guide_init(project: str, step: str, rev: str | None = None, notebook: str | None = None) -> dict:
    from .explain.guide import GuideError, scaffold, write_target

    p, reg, s, r = _guide_ctx(project, step, rev)
    target = write_target(p, r, step)
    if target.exists():
        return {"path": _display(p, target), "text": target.read_text(encoding="utf-8"), "existed": True}
    try:
        text = scaffold(p, reg, step, rev, notebook)
    except GuideError as exc:
        raise ToolError("invalid", str(exc)) from None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return {"path": _display(p, target), "text": text, "existed": False}


def _display(p: Project, path: Path) -> str:
    return path.relative_to(p.root).as_posix() if path.is_relative_to(p.root) else str(path)


@tool("guide_get", "讲解", "读一步的讲解：内容、可讲的 notebook、引用与数字的核对结果、术语。", "guide_view", project="项目 id 或目录", step="步骤编号", rev="轮次")
def guide_get(project: str, step: str, rev: str | None = None) -> dict:
    from .explain.guide import guide_view

    p, reg, _ = _loaded(project)
    return guide_view(p, reg, step, rev)


@tool("guide_check", "讲解", "核对讲解：引用的 notebook、单元格、行号存不存在，写的数字能不能在输出里找到。", "{errors, checked, found, missing}",
      project="项目 id 或目录", step="步骤编号", rev="轮次")
def guide_check(project: str, step: str, rev: str | None = None) -> dict:
    from .explain.guide import check_guide, load_guide

    p, reg, s, r = _guide_ctx(project, step, rev)
    guide, error, _, _ = load_guide(p, s, r)
    if error:
        raise ToolError("invalid", error)
    if guide is None:
        raise ToolError("not_found", f"步骤 {step} {r.id} 还没有讲解", "先 guide_init 再 guide_put")
    return check_guide(p, reg, s, r, guide)


@tool("guide_lint", "讲解", "体检讲解：用词、句子、篇幅、照搬。空列表就是通过。", "[{step, revision, issues}]", project="项目 id 或目录", step="只看某一步")
def guide_lint(project: str, step: str | None = None) -> list[dict]:
    from .explain.lint import lint_project

    p, reg, _ = _loaded(project)
    return [{"step": s, "revision": r, "issues": [str(i) for i in issues]} for s, r, issues in lint_project(p, reg, step) if issues]


@tool("guide_put", "讲解", "写入 guide.yaml 全文，并立刻核对（引用、数字）与体检（用词、句子、篇幅）。", "{path, checks, lint}",
      project="项目 id 或目录", step="步骤编号", text="guide.yaml 全文", rev="轮次")
def guide_put(project: str, step: str, text: str, rev: str | None = None) -> dict:
    from .explain.guide import GuideError, put_guide

    p, reg, _ = _loaded(project)
    try:
        target, report = put_guide(p, reg, step, text, rev)
    except GuideError as exc:
        raise ToolError("invalid", str(exc)) from None
    return {"path": _display(p, target), "checks": report, "lint": guide_lint(project, step)}


# ---------- 工具：术语与待决事项 ----------


@tool("vocabulary_get", "术语", "项目术语表（项目自带的 + 平台目录里的）。", "[{term, meaning, source, aliases, avoid}]", project="项目 id 或目录")
def vocabulary_get(project: str) -> list[dict]:
    from .progress.checks import load_vocab

    return load_vocab(_project(project)) or []


@tool("vocabulary_add", "术语", "登记一个术语（写明出处）；avoid 里的说法以后会被体检拦下。已有同名术语就更新。", "{term, path}",
      project="项目 id 或目录", term="术语", meaning="白话解释", source="出处：数据表字段、表名或既有对话", aliases="别名", avoid="不许再用的说法")
def vocabulary_add(project: str, term: str, meaning: str, source: str = "", aliases: list[str] | None = None, avoid: list[str] | None = None) -> dict:
    p = _project(project)
    name = p.config.vocabulary if p.config else "vocabulary.json"
    path = (p.root / name) if not p.readonly else (p.state_dir() / "vocabulary.json")
    data: dict = {"terms": []}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        data = loaded if isinstance(loaded, dict) else {"terms": loaded}
    terms = data.setdefault("terms", [])
    entry = {"term": term, "meaning": meaning, "source": source, "aliases": aliases or [], "avoid": avoid or []}
    for i, t in enumerate(terms):
        if t.get("term") == term:
            terms[i] = {**t, **{k: v for k, v in entry.items() if v}}
            break
    else:
        terms.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"term": term, "path": _display(p, path)}


@tool("decisions_list", "待决", "需要用户裁定的问题（平台记录的 + 项目文件里 decisions_required.json 的）。", "[pending]", project="项目 id 或目录")
def decisions_list(project: str) -> list[dict]:
    from .progress.tracker import TrackerStore, project_pending

    p, reg, _ = _loaded(project)
    return [*TrackerStore(p).list("pending"), *project_pending(p.root, reg)]


@tool("decisions_add", "待决", "记一个需要用户裁定的问题（不替用户裁定）。", "pending", project="项目 id 或目录", question="问题",
      recommendation="推荐答案", basis="依据", alternatives="备选差异", impact="影响范围", blocking="是否阻塞后续执行", step="关联步骤")
def decisions_add(project: str, question: str, recommendation: str = "", basis: str = "", alternatives: str = "",
                  impact: str = "", blocking: bool = False, step: str | None = None) -> dict:
    from .progress.tracker import TrackerStore

    return TrackerStore(_project(project)).create("pending", {"question": question, "recommendation": recommendation, "basis": basis,
                                                              "alternatives": alternatives, "impact": impact, "blocking": blocking, "step": step})


# ---------- 工具：核对 ----------


@tool("validate", "核对", "注册表校验；errors 为空才算通过。", "{ok, steps, issues}", project="项目 id 或目录")
def validate(project: str) -> dict:
    p, reg, issues = _loaded(project)
    return {"ok": not any(i.severity == "error" for i in issues), "steps": len(reg.steps), "issues": [i.to_dict() for i in issues]}


@tool("check", "核对", "交接前核对：告警 + 说明卡数字回产物重算 + 术语检查（同 dsflow check）。", "{ok, alerts, steps}", project="项目 id 或目录", step="只看某一步")
def check(project: str, step: str | None = None) -> dict:
    from .progress.alerts import compute_alerts
    from .progress.checks import load_vocab, step_checks
    from .tracking.store import RunStore

    p, reg, issues = _loaded(project)
    alerts = compute_alerts(p, reg, issues, RunStore(p).list(), verify=True)
    vocab = load_vocab(p)
    checks = {s.id: step_checks(p, reg, s.id, vocab) for s in reg.steps if not step or s.id == step}
    blocking = [a for a in alerts if a["level"] in ("critical", "serious")]
    mismatched = sum(1 for c in checks.values() if c.get("has_card") for x in c["numbers"]["items"] if x["status"] == "mismatch")
    return {"ok": not blocking and mismatched == 0, "alerts": alerts, "steps": checks}


# ---------- 工具：审批 ----------


@tool("approval_get", "审批", "一步的审批记录，以及现在等的是计划审批还是完成确认。", "{status, pending, entries}", project="项目 id 或目录", step="步骤编号")
def approval_get(project: str, step: str) -> dict:
    from .core.approval import approvals_view

    p, reg, _ = _loaded(project)
    return approvals_view(p, reg, step)


@tool("approval_decide", "审批", "记录用户在对话里的审批（用户说了才能调）：decision 为 approve / reject；kind 省略时按当前状态判定。平台会改状态并写审批记录。",
      "{from, to, record, entry, warnings}", project="项目 id 或目录", step="步骤编号", decision="approve / reject", note="用户原话", kind="approval / acceptance")
def approval_decide(project: str, step: str, decision: str, note: str = "", kind: str | None = None) -> dict:
    from .core.approval import decide, find_step, kind_for

    p, reg, _ = _loaded(project)
    return decide(p, reg, step, kind or kind_for(find_step(reg, step)), decision, note, source="MCP")


@tool("approval_withdraw", "审批", "撤回这一步最后一条审批（用户说填错了才能调）：状态改回表态之前，审批记录里追加一条「撤回」，记录从不删除。"
      "只能撤最后一条，且状态还停在那条记录留下的状态。",
      "{from, to, record, entry, withdrew}", project="项目 id 或目录", step="步骤编号", note="用户原话：为什么撤回")
def approval_withdraw(project: str, step: str, note: str = "") -> dict:
    from .core.approval import withdraw

    p, reg, _ = _loaded(project)
    return withdraw(p, reg, step, note, source="MCP")


@tool("approval_wait", "审批", "等用户在平台审批或确认：最多等 timeout 秒（上限 50，适合长轮询），到时未决返回 result=pending，再调一次即可。",
      "{result: approved|confirmed|rejected|pending, status, entry}", project="项目 id 或目录", step="步骤编号", timeout="最多等多少秒（≤ 50）")
def approval_wait(project: str, step: str, timeout: int = 50) -> dict:
    from .core.approval import wait_for

    p = _project(project)
    out = wait_for(p, step, "any", min(max(int(timeout), 1), 50), 1.0)
    if out["result"] == "timeout":
        out["result"] = "pending"
    return out


def protocol_markdown() -> str:
    """协议文档里的工具表，由登记表生成（docs/agent-protocol.md 的「工具」一节就是它）。"""
    doc = protocol_document()
    lines = [f"<!-- 由 `dsflow protocol --format markdown` 生成，协议 v{doc['protocol']}；不要手改 -->", ""]
    for group in dict.fromkeys(t["group"] for t in doc["tools"]):
        lines.append(f"### {group}")
        lines.append("")
        lines.append("| 工具 | 做什么 | 参数 | 返回 |")
        lines.append("|---|---|---|---|")
        for t in doc["tools"]:
            if t["group"] != group:
                continue
            params = "、".join(
                f"`{n}`{'' if n in t['params']['required'] else '（可选）'}" + (f"：{d['description']}" if d.get("description") else "")
                for n, d in t["params"]["properties"].items()) or "无"
            lines.append(f"| `{t['name']}` | {t['description']} | {params} | `{t['returns']}` |")
        lines.append("")
    return "\n".join(lines)


TOOL_NAMES = tuple(REGISTRY)
