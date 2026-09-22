"""运行环境采集：代码版本（git）、依赖版本（uv.lock 指纹与关键包）、解释器。"""

from __future__ import annotations

import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from ..core.hashing import sha256_file

KEY_PACKAGES = ("pandas", "numpy", "scikit-learn", "lightgbm", "xgboost", "duckdb", "pyarrow", "statsmodels")


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10,
                             encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def capture_env(root: Path) -> tuple[str | None, bool | None, dict[str, str]]:
    """返回 (commit, 工作区是否有未提交改动, 环境信息)。不是 git 仓库时 commit 与 dirty 为 None。"""
    commit = _git(root, "rev-parse", "HEAD")
    dirty = None
    if commit:
        status = _git(root, "status", "--porcelain", "--untracked-files=no")
        dirty = bool(status) if status is not None else None
    env = {"python": platform.python_version(), "platform": platform.platform(), "executable": sys.executable}
    lock = Path(root) / "uv.lock"
    if lock.is_file():
        env["uv_lock"] = sha256_file(lock)[:12]
    for name in KEY_PACKAGES:
        try:
            env[f"pkg:{name}"] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return commit, dirty, env
