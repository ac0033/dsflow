"""发现项目中的数据文件（只读遍历）。"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

DATA_FORMATS = {".csv": "csv", ".tsv": "csv", ".xlsx": "xlsx", ".parquet": "parquet"}
SKIP_DIRS = {".git", ".venv", ".uv-cache", "node_modules", "__pycache__", ".dsflow", ".pytest_cache", ".workbuddy"}
MAX_FILES = 5000


def data_format(path: Path) -> str | None:
    if path.name.startswith("~$"):  # Excel 打开时留下的锁文件
        return None
    return DATA_FORMATS.get(path.suffix.lower())


def discover(root: Path) -> list[dict]:
    root = Path(root)
    found: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            fmt = data_format(path)
            if fmt is None:
                continue
            st = path.stat()
            found.append({
                "path": path.relative_to(root).as_posix(),
                "format": fmt,
                "size": st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            })
            if len(found) >= MAX_FILES:
                return found
    return found


def attribute(files: list[dict], reg, datasets: list[dict]) -> list[dict]:
    """给每个数据文件标上归属：它落在哪个阶段、哪个步骤，是不是登记过的数据集。

    两条归属线，先后顺序是：文件放在某个步骤（或阶段）目录下 > 由某个步骤产出（登记数据集时写的 produced_by）。
    两条都对不上的（data/raw 这类全项目共用的文件）留空，项目总览就只列这些。
    """
    steps = sorted(getattr(reg, "steps", []) or [], key=lambda s: len(s.dir), reverse=True)
    stages = sorted(getattr(reg, "stages", []) or [], key=lambda s: len(s.dir), reverse=True)
    stage_name = {s.id: s.name for s in stages}
    stage_of_step = {s.id: s.stage for s in steps}
    produced: dict[str, str] = {}
    registered: dict[str, dict] = {}
    for d in datasets:
        for v in d["versions"]:
            registered[v["path"]] = {"dataset": d["name"], "data_stage": v.get("stage") or ""}
            if v.get("produced_by"):
                produced[v["path"]] = v["produced_by"]
    for f in files:
        path = f["path"]
        step_id, stage_id = None, None
        for s in steps:
            if s.dir and (path == s.dir or path.startswith(s.dir.rstrip("/") + "/")):
                step_id, stage_id = s.id, s.stage
                break
        if stage_id is None:
            for s in stages:
                if s.dir and path.startswith(s.dir.rstrip("/") + "/"):
                    stage_id = s.id
                    break
        if stage_id is None and path in produced:
            step_id = produced[path]
            stage_id = stage_of_step.get(step_id)
        f["step"] = step_id
        f["stage"] = stage_id
        f["stage_name"] = stage_name.get(stage_id, "") if stage_id is not None else ""
        f["dataset"] = registered.get(path, {}).get("dataset")
        f["data_stage"] = registered.get(path, {}).get("data_stage", "")
    return files
