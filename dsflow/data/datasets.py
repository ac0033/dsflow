"""数据集登记（轻量 DVC）：逻辑名 → 按内容哈希区分的版本序列，带阶段与血缘。

登记只记录路径与哈希，不复制数据。存放在 Project.state_dir()/datasets/<逻辑名>.json。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq

from ..core.project import Project
from ..core.schemas import DatasetVersion
from .cache import DataCache, read_json, write_json
from .engine import DataError

STAGE_ORDER = ["raw", "processed", "features", "splits", "model_input", "predictions", "other"]
STAGE_LABEL = {
    "raw": "原始", "processed": "处理后", "features": "特征", "splits": "划分",
    "model_input": "建模输入", "predictions": "预测结果", "other": "其他",
}
_NAME = re.compile(r"^[\w一-鿿.-]{1,80}$")


class DatasetStore:
    def __init__(self, project: Project):
        self.project = project
        self.cache = DataCache(project)
        self.dir = project.state_dir() / "datasets"

    def _file(self, name: str) -> Path:
        return self.dir / f"{name}.json"

    def list(self) -> list[dict]:
        if not self.dir.is_dir():
            return []
        out = []
        for path in sorted(self.dir.glob("*.json")):
            data = read_json(path)
            for v in data["versions"]:
                self._fill_shape(v)
            out.append(data)
        return out

    def get(self, name: str) -> dict | None:
        data = read_json(self._file(name))
        if data:
            for v in data["versions"]:
                self._fill_shape(v)
        return data

    def _fill_shape(self, version: dict) -> None:
        if version.get("rows") is not None:
            return
        try:
            ready = self.cache.parquet_if_ready(version["path"])
        except (FileNotFoundError, DataError):
            version["missing"] = True
            return
        if ready is not None:
            meta = pq.ParquetFile(ready).metadata
            version["rows"], version["columns"] = meta.num_rows, meta.num_columns

    def register(self, rel: str, name: str, stage: str = "raw", parents: list[str] | None = None,
                 produced_by: str | None = None, description: str = "", replaces: list[str] | None = None,
                 require_description: bool = True) -> dict:
        if not _NAME.match(name):
            raise DataError("数据集名只能用中文、字母、数字、下划线、点和连字符，最长 80 个字符")
        if stage not in STAGE_ORDER:
            raise DataError(f"阶段须为：{'、'.join(STAGE_ORDER)}")
        key, path, fmt = self.cache.source(rel)
        sha = self.cache.fingerprint(key)
        data = read_json(self._file(name)) or {"name": name, "description": "", "versions": []}
        text = description.strip()
        if text:
            data["description"] = text
        elif require_description and not (data.get("description") or "").strip():
            # 介绍是数据里文件名下面那行小字。新登记的数据不写就登记不进来，页面上才不会出现没人介绍的文件。
            # 只有 run.log_input 例外：它登记的是这次读了谁，读的人不一定说得清那份数据，改由告警提醒补写。
            raise DataError(f"登记 {name} 的同时要写一句介绍：它装的是什么、怎么来的、后面哪一步会用。"
                            "每份数据各写各的，页面上文件名下面那行小字就是它")
        latest = data["versions"][-1] if data["versions"] else None
        if latest and latest["sha256"] == sha and latest["path"] == key:
            if replaces and sorted(replaces) != sorted(latest.get("replaces") or []):
                latest["replaces"] = list(replaces)
                write_json(self._file(name), data)
            return {"dataset": data, "version": latest, "created": False}
        version = DatasetVersion(
            name=name, version=sha[:12], sha256=sha, path=key, format=fmt, size_bytes=path.stat().st_size,
            stage=stage, produced_by=produced_by, parents=parents or [], replaces=replaces or [],
            registered_at=datetime.now().isoformat(timespec="seconds"),
        ).model_dump()
        if fmt == "parquet":
            meta = pq.ParquetFile(path).metadata
            version["rows"], version["columns"] = meta.num_rows, meta.num_columns
        data["versions"].append(version)
        write_json(self._file(name), data)
        return {"dataset": data, "version": version, "created": True}

    def describe(self, name: str, description: str) -> dict:
        """补写或改写一份数据的介绍：数据里文件名下面那行小字就是它，每份数据各写各的。"""
        data = read_json(self._file(name))
        if data is None:
            raise DataError(f"数据集 {name} 还没有登记")
        text = description.strip()
        if not text:
            raise DataError("介绍不能是空的：写一句它装的是什么、怎么来的、后面哪一步会用")
        data["description"] = text
        write_json(self._file(name), data)
        return data

    def link(self, name: str, step: str, role: str = "读取") -> dict:
        """登记「某一步用了这张表、用途是什么」。校验型步骤不产出数据，只能靠这个挂上来。"""
        data = read_json(self._file(name))
        if data is None:
            raise DataError(f"数据集 {name} 还没有登记")
        used = [u for u in data.get("used_by") or [] if u.get("step") != step]
        used.append({"step": step, "role": role})
        data["used_by"] = sorted(used, key=lambda u: u["step"])
        write_json(self._file(name), data)
        return data

    def set_replaces(self, name: str, replaces: list[str]) -> dict:
        """声明「这张表登记后，哪些表就不再是有用的最终文件」：写在最新版本上，决定它们何时退出存量。"""
        data = read_json(self._file(name))
        if data is None:
            raise DataError(f"数据集 {name} 还没有登记")
        for old in replaces:
            if old == name:
                raise DataError("数据集不能替代自己")
            if not self._file(old).is_file():
                raise DataError(f"被替代的数据集 {old} 还没有登记")
        data["versions"][-1]["replaces"] = list(dict.fromkeys(replaces))
        write_json(self._file(name), data)
        return data

    def unlink(self, name: str, step: str) -> dict:
        data = read_json(self._file(name))
        if data is None:
            raise DataError(f"数据集 {name} 还没有登记")
        data["used_by"] = [u for u in data.get("used_by") or [] if u.get("step") != step]
        write_json(self._file(name), data)
        return data

    def lineage(self) -> dict:
        """数据血缘：数据集 → 产出步骤 → 数据集；没有登记产出步骤的，上游直接连到下游。"""
        chain = self.chain()
        nodes = {f"d:{c['name']}": {"id": f"d:{c['name']}", "type": "dataset", **c} for c in chain}
        edges: list[tuple[str, str]] = []
        for c in chain:
            target = f"d:{c['name']}"
            for p in c["parents"]:
                nodes.setdefault(f"d:{p}", {"id": f"d:{p}", "type": "dataset", "name": p, "missing": True})
            if c["produced_by"]:
                step = f"s:{c['produced_by']}"
                nodes.setdefault(step, {"id": step, "type": "step", "step": c["produced_by"]})
                edges.append((step, target))
                edges += [(f"d:{p}", step) for p in c["parents"]]
            else:
                edges += [(f"d:{p}", target) for p in c["parents"]]
        return {"nodes": list(nodes.values()), "edges": [{"from": a, "to": b} for a, b in dict.fromkeys(edges)]}

    def chain(self) -> list[dict]:
        """数据演变链：每个数据集的最新版本，按阶段顺序排列，带血缘与产出步骤。"""
        items = []
        for data in self.list():
            latest = data["versions"][-1]
            items.append({
                "name": data["name"], "description": data.get("description", ""),
                "stage": latest["stage"], "stage_label": STAGE_LABEL.get(latest["stage"], latest["stage"]),
                "version": latest["version"], "path": latest["path"], "rows": latest.get("rows"),
                "columns": latest.get("columns"), "produced_by": latest.get("produced_by"),
                "parents": latest.get("parents", []), "replaces": latest.get("replaces") or [],
                "version_count": len(data["versions"]),
                "registered_at": latest["registered_at"], "used_by": data.get("used_by") or [],
                "format": latest.get("format"), "size_bytes": latest.get("size_bytes"),
            })
        items.sort(key=lambda x: (STAGE_ORDER.index(x["stage"]) if x["stage"] in STAGE_ORDER else 99,
                                  x["registered_at"]))
        return items
