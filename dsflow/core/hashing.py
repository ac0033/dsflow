"""内容哈希：数据版本号与只读保证都以 SHA256 为准。"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 1 << 20
DEFAULT_EXCLUDE = frozenset({".git", ".venv", ".uv-cache", "__pycache__", "node_modules", ".pytest_cache"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def tree_manifest(root: Path, exclude_dirs: frozenset[str] = DEFAULT_EXCLUDE) -> dict[str, dict]:
    """目录下全部文件的 {相对路径: {size, sha256}}，用于证明某次操作前后目录未被改动。"""
    root = Path(root)
    manifest: dict[str, dict] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in exclude_dirs for part in rel.parts) or not path.is_file():
            continue
        manifest[rel.as_posix()] = {"size": path.stat().st_size, "sha256": sha256_file(path)}
    return manifest
