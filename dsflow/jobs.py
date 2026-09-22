"""后台任务：转换、画像、对比这类可能要几十秒的操作放到线程池，前端轮询进度。

同一件事（同一个 key）正在跑时不重复提交；最多 2 个并发，避免大数据任务互相抢内存。
"""

from __future__ import annotations

import threading
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

MAX_KEEP = 200


class JobManager:
    def __init__(self, workers: int = 2):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dsflow-job")
        self._jobs: dict[str, dict] = {}
        self._by_key: dict[str, str] = {}
        self._lock = threading.Lock()

    def submit(self, key: str, kind: str, fn: Callable[..., Any], *args: Any) -> dict:
        with self._lock:
            existing = self._by_key.get(key)
            if existing and self._jobs[existing]["status"] in ("queued", "running"):
                return self.view(existing)
            job_id = uuid.uuid4().hex[:12]
            self._jobs[job_id] = {
                "id": job_id, "key": key, "kind": kind, "status": "queued", "progress": None,
                "message": "排队中", "result": None, "error": None,
                "created_at": datetime.now().isoformat(timespec="seconds"), "ended_at": None,
            }
            self._by_key[key] = job_id
            self._trim()
        self._pool.submit(self._run, job_id, fn, args)
        return self.view(job_id)

    def _run(self, job_id: str, fn: Callable[..., Any], args: tuple) -> None:
        job = self._jobs[job_id]

        def progress(fraction: float | None, message: str) -> None:
            job["progress"], job["message"] = fraction, message

        job["status"], job["message"] = "running", "开始"
        try:
            job["result"] = fn(*args, progress)
            job["status"], job["progress"], job["message"] = "succeeded", 1.0, "完成"
        except Exception as exc:  # noqa: BLE001 — 任务错误要回传给界面
            job["status"], job["error"] = "failed", str(exc) or type(exc).__name__
            job["message"] = "失败"
            job["trace"] = traceback.format_exc(limit=5)
        finally:
            job["ended_at"] = datetime.now().isoformat(timespec="seconds")

    def view(self, job_id: str) -> dict:
        job = self._jobs[job_id]
        return {k: v for k, v in job.items() if k != "trace"}

    def get(self, job_id: str) -> dict | None:
        return self.view(job_id) if job_id in self._jobs else None

    def _trim(self) -> None:
        done = [j for j in self._jobs.values() if j["status"] in ("succeeded", "failed")]
        for job in done[: max(0, len(self._jobs) - MAX_KEEP)]:
            self._jobs.pop(job["id"], None)
