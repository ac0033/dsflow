"""运行追踪 API：列表、详情（含复现卡片）、日志与实时日志流、图表、平台重跑。

只读接入的项目不能从平台重跑：重跑会执行项目代码，代码会写项目目录。
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from ..index.db import PlatformIndex
from ..tracking.runner import execute, prepare
from ..tracking.store import RunStore, reproduce
from .deps import get_project

LOG_TAIL = 2_000_000
_FIGURE = re.compile(r"^[\w一-鿿.-]+\.png$")


def _read(path: Path, pos: int, final: bool) -> bytes:
    if not path.is_file():
        return b""
    with open(path, "rb") as f:
        f.seek(pos)
        data = f.read(1 << 20)
    if final or not data:
        return data
    cut = data.rfind(b"\n")
    return data[: cut + 1] if cut >= 0 else b""


def run_router(index: PlatformIndex) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{project_id}/runs")

    def open_store(project_id: str):
        project = get_project(index, project_id)
        return project, RunStore(project)

    def load(store: RunStore, run_id: str) -> dict:
        try:
            run = store.get(run_id)
        except ValueError:
            run = None
        if run is None:
            raise HTTPException(404, "运行记录不存在")
        return run

    @router.get("")
    def list_runs(project_id: str, step: str | None = None) -> list[dict]:
        _, store = open_store(project_id)
        return store.list(step)

    @router.get("/{run_id}")
    def detail(project_id: str, run_id: str) -> dict:
        project, store = open_store(project_id)
        run = load(store, run_id)
        log = store.log_path(run_id)
        return {**run, "reproduce": reproduce(run), "readonly": project.readonly,
                "log_size": log.stat().st_size if log.is_file() else 0}

    @router.get("/{run_id}/log")
    def log(project_id: str, run_id: str) -> dict:
        _, store = open_store(project_id)
        run = load(store, run_id)
        path = store.log_path(run_id)
        size = path.stat().st_size if path.is_file() else 0
        start = max(0, size - LOG_TAIL)
        text = _read(path, start, final=True).decode("utf-8", "replace") if size else ""
        return {"text": text, "truncated": start > 0, "size": size, "done": run["status"] != "running"}

    @router.get("/{run_id}/stream")
    async def stream(project_id: str, run_id: str) -> StreamingResponse:
        _, store = open_store(project_id)
        load(store, run_id)
        path = store.log_path(run_id)

        async def events():
            pos = 0
            while True:
                chunk = _read(path, pos, final=False)
                if chunk:
                    pos += len(chunk)
                    yield f"data: {json.dumps({'text': chunk.decode('utf-8', 'replace')}, ensure_ascii=False)}\n\n"
                    continue
                run = store.get(run_id)
                if run["status"] != "running":
                    rest = _read(path, pos, final=True)
                    if rest:
                        yield f"data: {json.dumps({'text': rest.decode('utf-8', 'replace')}, ensure_ascii=False)}\n\n"
                    yield f"event: end\ndata: {json.dumps({'status': run['status'], 'exit_code': run.get('exit_code')})}\n\n"
                    return
                await asyncio.sleep(0.4)

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @router.get("/{run_id}/figure")
    def figure(project_id: str, run_id: str, file: str) -> FileResponse:
        _, store = open_store(project_id)
        load(store, run_id)
        path = store.artifacts_dir(run_id) / file
        if not _FIGURE.match(file) or not path.is_file():
            raise HTTPException(404, "图表不存在")
        return FileResponse(path, media_type="image/png")

    @router.post("/{run_id}/rerun", status_code=201)
    def rerun(project_id: str, run_id: str) -> dict:
        project, store = open_store(project_id)
        run = load(store, run_id)
        if project.readonly:
            raise HTTPException(403, "只读接入的项目不能从平台重跑：重跑会执行项目代码并写入项目目录。请在命令行用 dsflow run 自行运行。")
        if not run.get("argv"):
            raise HTTPException(400, "这条运行没有记录启动命令，无法重跑")
        new = prepare(project, run["step"], run["argv"], hypothesis=run.get("hypothesis", ""),
                      revision=run.get("revision"), rerun_of=run_id, source="ui", cwd=run.get("cwd"))
        threading.Thread(target=execute, args=(project, new["run_id"]), daemon=True, name=f"dsflow-run-{new['run_id']}").start()
        return new

    return router
