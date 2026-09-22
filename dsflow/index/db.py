"""平台索引（SQLite）：只记录登记了哪些项目及其步骤概况，随时可由项目文件重建。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ..core.project import Project, ProjectError
from ..core.schemas import Registry
from ..core.validate import ValidationIssue
from ..paths import dsflow_home

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root TEXT NOT NULL,
    readonly INTEGER NOT NULL DEFAULT 1,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS step_index(
    project_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    stage INTEGER,
    ord INTEGER,
    title TEXT,
    status TEXT,
    current_revision TEXT,
    revision_count INTEGER,
    PRIMARY KEY(project_id, step_id)
);
CREATE TABLE IF NOT EXISTS scans(
    project_id TEXT PRIMARY KEY,
    scanned_at TEXT,
    step_count INTEGER,
    error_count INTEGER
);
"""


def open_for_write(root: str | Path) -> Project:
    """SDK 与 dsflow run 用：已登记的项目沿用登记时的读写模式（只读项目的运行记录写到平台目录）；
    未登记的项目由它自己的代码在记录，视为可写（写到项目的 .dsflow/）。"""
    project = Project(root, readonly=False)
    row = PlatformIndex().get_project(project.id)
    return Project(root, row["readonly"]) if row else project


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class PlatformIndex:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else dsflow_home() / "platform.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._tx() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_project(self, root: str | Path, readonly: bool = True) -> dict:
        project = Project(root, readonly)
        project.load_registry_raw()  # 没有注册表的目录不允许登记
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO projects(id, name, root, readonly, added_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, readonly=excluded.readonly",
                (project.id, project.name, str(project.root), int(readonly), _now()),
            )
        self.reindex(project)
        return self.get_project(project.id)

    def remove_project(self, project_id: str) -> bool:
        """只注销登记，绝不删除项目文件。"""
        with self._tx() as conn:
            removed = conn.execute("DELETE FROM projects WHERE id=?", (project_id,)).rowcount
            conn.execute("DELETE FROM step_index WHERE project_id=?", (project_id,))
            conn.execute("DELETE FROM scans WHERE project_id=?", (project_id,))
        return removed > 0

    def list_projects(self) -> list[dict]:
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT p.*, s.scanned_at, s.step_count, s.error_count FROM projects p "
                "LEFT JOIN scans s ON s.project_id = p.id ORDER BY p.added_at"
            ).fetchall()
            counts = conn.execute(
                "SELECT project_id, status, COUNT(*) AS n FROM step_index GROUP BY project_id, status"
            ).fetchall()
        by_project: dict[str, dict[str, int]] = {}
        for c in counts:
            by_project.setdefault(c["project_id"], {})[c["status"]] = c["n"]
        return [self._row(r, by_project.get(r["id"], {})) for r in rows]

    def get_project(self, project_id: str) -> dict | None:
        return next((p for p in self.list_projects() if p["id"] == project_id), None)

    def open_project(self, project_id: str) -> Project:
        row = self.get_project(project_id)
        if row is None:
            raise KeyError(project_id)
        return Project(row["root"], row["readonly"])

    def reindex(self, project: Project) -> tuple[Registry | None, list[ValidationIssue]]:
        try:
            reg, issues = project.load()
        except ProjectError as exc:
            reg, issues = None, [ValidationIssue("registry", str(exc))]
        errors = sum(1 for i in issues if i.severity == "error")
        with self._tx() as conn:
            conn.execute("DELETE FROM step_index WHERE project_id=?", (project.id,))
            if reg:
                conn.executemany(
                    "INSERT OR REPLACE INTO step_index VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (project.id, s.id, s.stage, s.order, s.title, s.status, s.current_revision,
                         len(s.revisions))
                        for s in reg.steps
                    ],
                )
            conn.execute(
                "INSERT INTO scans VALUES (?, ?, ?, ?) ON CONFLICT(project_id) DO UPDATE SET "
                "scanned_at=excluded.scanned_at, step_count=excluded.step_count, error_count=excluded.error_count",
                (project.id, _now(), len(reg.steps) if reg else 0, errors),
            )
        return reg, issues

    @staticmethod
    def _row(row: sqlite3.Row, status_counts: dict[str, int]) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "root": row["root"],
            "readonly": bool(row["readonly"]),
            "added_at": row["added_at"],
            "scanned_at": row["scanned_at"],
            "step_count": row["step_count"],
            "error_count": row["error_count"],
            "status_counts": status_counts,
        }
