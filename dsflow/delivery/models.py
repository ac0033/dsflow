"""模型登记：模型文件按内容哈希区分版本，关联产出它的运行——数据版本、代码版本、指标都从运行记录追溯。

状态：candidate 候选 → accepted 已验收 → delivered 已交付，可以退回上一级；每次变更写明理由，记入历史。
往上走之前要过门槛（见 gates）；门槛不满足时拒绝，并说清缺什么。
存放：<状态目录>/models/<模型名>.json（只读接入的项目在平台目录）。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..core.hashing import sha256_file
from ..core.project import Project, ProjectError
from ..core.schemas import MODEL_STATUS_LABEL, STATUS_LABEL, ModelVersion, StatusChange
from ..data.cache import read_json, write_json
from ..tracking.store import RunStore

NAME = re.compile(r"^[\w一-鿿.-]{1,80}$")
ORDER = ["candidate", "accepted", "delivered"]
TRANSITIONS = {("candidate", "accepted"), ("accepted", "delivered"), ("accepted", "candidate"), ("delivered", "accepted")}
NEXT = {"candidate": "accepted", "accepted": "delivered", "delivered": "delivered"}
RUN_KEYS = ("run_id", "step", "revision", "status", "validity", "hypothesis", "conclusion", "metrics", "params",
            "inputs", "git_commit", "git_dirty", "env", "argv", "started_at")
RUN_STATUS = {"succeeded": "成功", "failed": "失败", "running": "还在运行"}


class ModelError(Exception):
    pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ModelStore:
    def __init__(self, project: Project):
        self.project = project
        self.dir = project.state_dir() / "models"
        self.runs = RunStore(project)

    def _file(self, name: str) -> Path:
        if not NAME.match(name or ""):
            raise ModelError("模型名只能用中文、字母、数字、下划线、点和连字符，最长 80 个字符")
        return self.dir / f"{name}.json"

    def _read(self, name: str) -> dict:
        data = read_json(self._file(name))
        if data is None:
            raise KeyError(name)
        return data

    # ---------- 登记与读取 ----------

    def register(self, rel: str, name: str, run_id: str | None = None, description: str = "") -> dict:
        file = self._file(name)
        try:
            path = self.project.resolve(rel)
        except ProjectError as exc:
            raise ModelError(str(exc)) from exc
        if not path.is_file():
            raise FileNotFoundError(rel)
        run = None
        if run_id:
            run = self.runs.get(run_id)
            if run is None:
                raise ModelError(f"运行 {run_id} 不存在")
        sha = sha256_file(path)
        st = path.stat()
        data = read_json(file) or {"name": name, "description": description, "versions": []}
        if description and not data.get("description"):
            data["description"] = description
        same = next((v for v in data["versions"] if v["sha256"] == sha), None)
        if same:
            # 重新训练得到完全相同的文件：还是候选时关联到最新这次运行；已验收 / 已交付的不改，保持验收时的依据
            if run and same["status"] == "candidate" and same.get("run_id") != run_id:
                same.update(run_id=run_id, step=run["step"], mtime_ns=st.st_mtime_ns)
                same["history"].append(StatusChange(status="candidate", at=_now(),
                                                    note=f"运行 {run_id} 重新产出了同样内容的文件，关联改为这次运行").model_dump())
                write_json(file, data)
            return {"model": data, "version": same, "created": False}
        now = _now()
        version = ModelVersion(
            name=name, version=sha[:12], sha256=sha, path=path.relative_to(self.project.root).as_posix(),
            size_bytes=st.st_size, mtime_ns=st.st_mtime_ns, run_id=run_id, step=run["step"] if run else None,
            description=description, registered_at=now, history=[StatusChange(status="candidate", at=now, note="登记为候选")],
        ).model_dump()
        data["versions"].append(version)
        write_json(file, data)
        return {"model": data, "version": version, "created": True}

    def enrich(self, v: dict) -> dict:
        run = self.runs.get(v["run_id"]) if v.get("run_id") else None
        return {**v, "status_label": MODEL_STATUS_LABEL[v["status"]], "run": {k: run.get(k) for k in RUN_KEYS} if run else None}

    def list(self) -> list[dict]:
        if not self.dir.is_dir():
            return []
        out = []
        for f in sorted(self.dir.glob("*.json")):
            data = read_json(f)
            out.append({**data, "versions": [self.enrich(v) for v in data["versions"]]})
        return out

    def get(self, name: str, version: str) -> dict:
        v = next((x for x in self._read(name)["versions"] if x["version"] == version), None)
        if v is None:
            raise KeyError(f"{name} {version}")
        return self.enrich(v)

    def latest(self, name: str) -> dict:
        return self.enrich(self._read(name)["versions"][-1])

    # ---------- 文件核对 ----------

    def quick_state(self, v: dict) -> str:
        """不算哈希：missing / maybe_changed（大小或修改时间与登记时不同）/ same。"""
        path = self.project.root / v["path"]
        if not path.is_file():
            return "missing"
        st = path.stat()
        if st.st_size != v["size_bytes"] or st.st_mtime_ns != v.get("mtime_ns"):
            return "maybe_changed"
        return "same"

    def file_matches(self, v: dict) -> tuple[bool, str]:
        path = self.project.root / v["path"]
        if not path.is_file():
            return False, f"文件 {v['path']} 不见了"
        if sha256_file(path) != v["sha256"]:
            return False, "文件内容与登记时不同（被覆盖过）"
        return True, "与登记时一致"

    # ---------- 门槛与状态 ----------

    def gates(self, v: dict, target: str) -> list[dict]:
        """升到 target 之前要满足的条件。blocking=False 的只提示、不拦。"""
        from .checklist import check_checklist

        out: list[dict] = []

        def add(code: str, label: str, passed: bool, detail: str, blocking: bool = True) -> None:
            out.append({"code": code, "label": label, "passed": bool(passed), "detail": detail, "blocking": blocking})

        run = v.get("run")
        add("run", "有产出运行（数据版本、代码版本、指标可追溯）", run is not None,
            f"运行 {run['run_id']}" if run else "登记时没有关联运行，无法追溯训练数据与指标")
        if run:
            add("run_ok", "产出运行成功", run["status"] == "succeeded", RUN_STATUS.get(run["status"], run["status"]))
            add("validity", "运行结论为「有效」", run.get("validity") == "有效", f"结论：{run.get('validity') or '未判断'}")
            metrics = run.get("metrics") or {}
            add("metrics", "记录了评估指标", bool(metrics),
                "、".join(f"{k} = {val}" for k, val in list(metrics.items())[:3]) or "运行没有记录指标")
            inputs = run.get("inputs") or []
            add("data", "训练数据已登记版本", bool(inputs),
                "、".join(f"{d['name']} {d['version']}" for d in inputs) or "运行没有登记输入数据")
            code_ok = bool(run.get("git_commit")) and not run.get("git_dirty")
            add("code", "代码版本可还原", code_ok,
                f"commit {run['git_commit'][:10]}" if code_ok else
                ("运行时有未提交的改动" if run.get("git_commit") else "运行时不是 git 仓库"), blocking=False)
        ok, detail = self.file_matches(v)
        add("file", "模型文件与登记时一致", ok, detail)
        if v.get("step"):
            try:
                reg, _ = self.project.load()
            except ProjectError:
                reg = None
            step = next((s for s in reg.steps if s.id == v["step"]), None) if reg else None
            if step:
                add("step", "产出步骤已通过验收", step.status == "done", f"注册表状态：{STATUS_LABEL[step.status]}", blocking=False)
        if target == "delivered":
            c = check_checklist(self.project, v)
            add("checklist", "交付清单齐全", c["complete"], f"交付清单{c['summary']}")
        return out

    def promote(self, name: str, version: str, to: str, note: str) -> dict:
        if to not in MODEL_STATUS_LABEL:
            raise ModelError(f"状态只能是 {' / '.join(MODEL_STATUS_LABEL)}")
        if not (note or "").strip():
            raise ModelError("状态变更要写明理由（会记入历史）")
        data = self._read(name)
        v = next((x for x in data["versions"] if x["version"] == version), None)
        if v is None:
            raise KeyError(f"{name} {version}")
        frm = v["status"]
        if (frm, to) not in TRANSITIONS:
            raise ModelError(f"不能从「{MODEL_STATUS_LABEL[frm]}」改为「{MODEL_STATUS_LABEL[to]}」"
                             "（顺序是 候选 → 已验收 → 已交付，可以退回上一级）")
        if ORDER.index(to) > ORDER.index(frm):
            failing = [g for g in self.gates(self.enrich(v), to) if g["blocking"] and not g["passed"]]
            if failing:
                raise ModelError(f"还不能标为「{MODEL_STATUS_LABEL[to]}」：" +
                                 "；".join(f"{g['label']}（{g['detail']}）" for g in failing))
        v["status"] = to
        v["history"].append(StatusChange(status=to, at=_now(), note=note.strip()).model_dump())
        write_json(self._file(name), data)
        return self.enrich(v)
