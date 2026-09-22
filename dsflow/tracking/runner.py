"""dsflow run 与平台重跑的执行器：在子进程里运行命令，日志落盘，结束时写入状态与退出码。

子进程通过环境变量 DSFLOW_RUN_ID / DSFLOW_PROJECT 找到这条运行记录，SDK 会写进同一条记录。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..core.project import Project
from .store import RunStore


def resolve_argv(argv: list[str]) -> list[str]:
    exe = shutil.which(argv[0])
    return [exe or argv[0], *argv[1:]]


def prepare(project: Project, step: str, argv: list[str], *, hypothesis: str = "", revision: str | None = None,
            rerun_of: str | None = None, source: str = "cli", cwd: str | None = None) -> dict:
    if not argv:
        raise ValueError("没有要运行的命令")
    return RunStore(project).create(step, revision=revision, hypothesis=hypothesis, argv=argv, cwd=cwd,
                                    source=source, rerun_of=rerun_of)


def execute(project: Project, run_id: str, on_line: Callable[[str], None] | None = None) -> dict:
    store = RunStore(project)
    run = store.get(run_id)
    run["pid"] = os.getpid()
    store.save(run)
    env = {**os.environ, "DSFLOW_RUN_ID": run_id, "DSFLOW_PROJECT": str(project.root),
           "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    log = store.log_path(run_id)
    cwd = run.get("cwd") if run.get("cwd") and Path(run["cwd"]).is_dir() else str(project.root)
    try:
        proc = subprocess.Popen(resolve_argv(run["argv"]), cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as exc:
        log.write_text(f"无法启动命令：{exc}\n", encoding="utf-8")
        return store.finish(run_id, "failed", error=f"无法启动命令：{exc}")
    with open(log, "wb") as f:
        for line in iter(proc.stdout.readline, b""):
            f.write(line)
            f.flush()
            if on_line:
                on_line(line.decode("utf-8", "replace"))
    code = proc.wait()
    return store.finish(run_id, "succeeded" if code == 0 else "failed", exit_code=code,
                        error=None if code == 0 else f"命令退出码 {code}")
