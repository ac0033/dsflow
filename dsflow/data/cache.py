"""项目数据缓存：文件指纹（SHA256）、Parquet 转换结果、画像结果。

缓存放在 Project.state_dir()/cache/：只读项目在 DSFLOW_HOME 下，项目目录不落文件。
Parquet 源文件直接读取，不复制；CSV/XLSX 按内容哈希转换一次，内容不变就复用。
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from ..core.hashing import sha256_file
from ..core.project import Project
from .convert import Progress, _noop, convert
from .engine import DataError
from .files import data_format

_LOCK = threading.Lock()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}.{threading.get_ident()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


class DataCache:
    def __init__(self, project: Project):
        self.project = project
        self.dir = project.state_dir() / "cache"

    # ---------- 源文件与指纹 ----------

    def source(self, rel: str) -> tuple[str, Path, str]:
        path = self.project.resolve(rel)
        if not path.is_file():
            raise FileNotFoundError(rel)
        fmt = data_format(path)
        if fmt is None:
            raise DataError(f"不支持的数据格式：{path.suffix or '无后缀'}（支持 csv / tsv / xlsx / parquet）")
        return path.relative_to(self.project.root).as_posix(), path, fmt

    def _book_path(self) -> Path:
        return self.dir / "fingerprints.json"

    def known_fingerprint(self, rel: str) -> str | None:
        """只查已记录的指纹（大小与修改时间都没变才算），不计算哈希。"""
        key, path, _ = self.source(rel)
        entry = read_json(self._book_path(), {}).get(key)
        st = path.stat()
        if entry and entry["size"] == st.st_size and entry["mtime_ns"] == st.st_mtime_ns:
            return entry["sha256"]
        return None

    def fingerprint(self, rel: str) -> str:
        known = self.known_fingerprint(rel)
        if known:
            return known
        key, path, _ = self.source(rel)
        st = path.stat()
        sha = sha256_file(path)
        with _LOCK:
            book = read_json(self._book_path(), {})
            book[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha}
            write_json(self._book_path(), book)
        return sha

    # ---------- Parquet ----------

    def _converted(self, sha: str) -> Path:
        return self.dir / "parquet" / f"{sha[:16]}.parquet"

    def parquet_if_ready(self, rel: str) -> Path | None:
        """不计算哈希地判断是否已可浏览：Parquet 源直接可用；其他格式看指纹与转换结果。"""
        _, path, fmt = self.source(rel)
        if fmt == "parquet":
            return path
        sha = self.known_fingerprint(rel)
        if sha and self._converted(sha).is_file():
            return self._converted(sha)
        return None

    def parquet_for_sha(self, sha: str) -> Path | None:
        """按登记时的哈希找那一版的 Parquet 缓存：源文件后来被新一版覆盖了，旧版本的行列数照样查得到。"""
        if not sha:
            return None
        dst = self._converted(sha)
        return dst if dst.is_file() else None

    def prepare(self, rel: str, progress: Progress = _noop) -> Path:
        _, path, fmt = self.source(rel)
        if fmt == "parquet":
            return path
        progress(None, "计算文件指纹")
        sha = self.fingerprint(rel)
        dst = self._converted(sha)
        if dst.is_file():
            return dst
        started = time.perf_counter()
        meta = convert(path, fmt, dst, progress)
        write_json(dst.with_suffix(".json"), {
            **meta,
            "source": rel,
            "sha256": sha,
            "converted_at": datetime.now().isoformat(timespec="seconds"),
            "seconds": round(time.perf_counter() - started, 2),
        })
        return dst

    def conversion_meta(self, rel: str) -> dict | None:
        ready = self.parquet_if_ready(rel)
        if ready is None or ready.parent != self.dir / "parquet":
            return None
        return read_json(ready.with_suffix(".json"))

    # ---------- 画像 ----------

    def profile_path(self, rel: str) -> Path:
        return self.dir / "profiles" / f"{self.fingerprint(rel)[:16]}.json"

    def cached_profile(self, rel: str) -> dict | None:
        from .profile import PROFILE_VERSION

        sha = self.known_fingerprint(rel)
        if sha is None:
            return None
        data = read_json(self.dir / "profiles" / f"{sha[:16]}.json")
        return data if data and data.get("version") == PROFILE_VERSION else None
