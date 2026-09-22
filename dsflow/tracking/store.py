"""运行记录的存取：<状态目录>/runs/<run_id>/{run.json, log.txt, artifacts/}。

状态目录见 Project.state_dir()：可写项目在项目内 .dsflow/，只读项目在平台目录。
记录运行的进程已经不在、却没写入最终状态的运行（被中止、崩溃），读取时会标为失败。
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from ..core.project import Project
from ..core.schemas import Run
from ..data.cache import read_json, write_json
from .env import capture_env

_RUN_ID = re.compile(r"^[\w.-]{1,80}$")
STALE_NOTE = "记录运行的进程已经结束，但没有写入最终结果（可能被中止或崩溃）"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def cmdline(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


def pid_alive(pid: int | None) -> bool:
    """进程是否还在。Windows 上不能用 os.kill(pid, 0)——那会直接结束目标进程。"""
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunStore:
    def __init__(self, project: Project):
        self.project = project
        self.dir = project.state_dir() / "runs"

    def _run_dir(self, run_id: str) -> Path:
        if not _RUN_ID.match(run_id or ""):
            raise ValueError(f"运行编号不合法：{run_id!r}")
        return self.dir / run_id

    def log_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "log.txt"

    def artifacts_dir(self, run_id: str) -> Path:
        path = self._run_dir(run_id) / "artifacts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create(self, step: str, *, revision: str | None = None, hypothesis: str = "", argv: list[str] | None = None,
               cwd: str | None = None, source: str = "sdk", rerun_of: str | None = None) -> dict:
        commit, dirty, env = capture_env(self.project.root)
        run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
        run = Run(
            run_id=run_id, step=step, revision=revision, command=cmdline(argv or []), argv=list(argv or []),
            cwd=cwd or str(self.project.root), source=source, rerun_of=rerun_of, pid=os.getpid(), started_at=now(),
            git_commit=commit, git_dirty=dirty, env=env, hypothesis=hypothesis,
        ).model_dump()
        self.save(run)
        return run

    def save(self, run: dict) -> None:
        write_json(self._run_dir(run["run_id"]) / "run.json", run)

    def get(self, run_id: str) -> dict | None:
        try:
            run = read_json(self._run_dir(run_id) / "run.json")
        except ValueError:
            return None
        return self._fix_stale(run) if run else None

    def list(self, step: str | None = None) -> list[dict]:
        if not self.dir.is_dir():
            return []
        runs = []
        for d in self.dir.iterdir():
            run = read_json(d / "run.json") if d.is_dir() else None
            if run and (step is None or run.get("step") == step):
                runs.append(self._fix_stale(run))
        return sorted(runs, key=lambda r: r["started_at"], reverse=True)

    def finish(self, run_id: str, status: str, exit_code: int | None = None, error: str | None = None) -> dict:
        run = read_json(self._run_dir(run_id) / "run.json")
        run["status"] = status
        run["ended_at"] = now()
        run["duration_s"] = round((datetime.now() - datetime.fromisoformat(run["started_at"])).total_seconds(), 2)
        if exit_code is not None:
            run["exit_code"] = exit_code
        if error and not run.get("error"):
            run["error"] = error
        self.save(run)
        return run

    def _fix_stale(self, run: dict) -> dict:
        if run.get("status") == "running" and run.get("pid") != os.getpid() and not pid_alive(run.get("pid")):
            run["status"] = "failed"
            run["error"] = run.get("error") or STALE_NOTE
            run["ended_at"] = run.get("ended_at") or now()
            self.save(run)
        return run


def reproduce(run: dict) -> dict:
    """复现卡片：还原代码、依赖、核对输入数据哈希、重跑命令；做不到精确还原的地方如实说明。"""
    commands, warnings = [], []
    if run.get("git_commit"):
        commands.append(f"git checkout {run['git_commit']}")
        if run.get("git_dirty"):
            warnings.append("运行时工作区有未提交的改动：按 commit 只能还原到最近一次提交，改动部分无法还原。")
    else:
        warnings.append("运行时项目不是 git 仓库（或找不到 git），代码版本无法精确还原。")
    if run.get("env", {}).get("uv_lock"):
        commands.append(f"uv sync    # 按 uv.lock 还原依赖（锁文件指纹 {run['env']['uv_lock']}）")
    for ref in run.get("inputs", []):
        if ref.get("sha256"):
            commands.append(f'uv run dsflow data verify . "{ref["path"]}" {ref["sha256"]}')
    if run.get("argv"):
        commands.append(f"uv run dsflow run {run['step']} -- {cmdline(run['argv'])}")
    else:
        warnings.append("没有记录启动命令，无法直接重跑。")
    return {"commands": commands, "warnings": warnings}
