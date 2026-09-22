"""数据视图 API：发现与登记、准备（转换）、分页浏览、抽样、只读 SQL、画像、对比、不变量检查。

耗时操作（转换、画像、对比）走后台任务，返回任务对象，前端轮询 /api/jobs/{id}。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..core.project import Project, ProjectError
from ..core.schemas import InvariantCheck
from ..data import browse, compare, invariants, peek as peek_data, steptables
from ..data.cache import DataCache
from ..data.service import ensure_profile
from ..data.datasets import STAGE_LABEL, STAGE_ORDER, DatasetStore
from ..data.engine import DataError, QueryError, slot
from ..data.files import attribute, discover
from ..index.db import PlatformIndex
from ..jobs import JobManager
from .deps import get_project


class RegisterIn(BaseModel):
    path: str
    name: str
    stage: str = "raw"
    parents: list[str] = []
    produced_by: str | None = None
    description: str = ""
    replaces: list[str] = []


class PathIn(BaseModel):
    path: str


class SqlIn(BaseModel):
    path: str
    sql: str


class CompareIn(BaseModel):
    a: str
    b: str
    key: list[str] = []
    segment: str | None = None


class DistributionIn(BaseModel):
    a: str
    b: str
    column: str


class ColumnsIn(BaseModel):
    """要查来历的那几列（一次问一张表的几列）。"""

    columns: list[str] = []
    rev: str | None = None


class ChecksIn(BaseModel):
    a: str
    b: str
    checks: list[InvariantCheck]


def _sub(progress: Callable, lo: float, hi: float) -> Callable:
    return lambda f, m: progress(None if f is None else lo + (hi - lo) * f, m)


def _prepare_job(cache: DataCache, rel: str, progress: Callable) -> dict:
    with slot():
        parquet = cache.prepare(rel, progress)
        return {"path": rel, "rows": browse.row_count(parquet)}


def _profile_job(cache: DataCache, rel: str, progress: Callable) -> dict:
    with slot():
        return ensure_profile(cache, rel, progress)


def _compare_job(cache: DataCache, body: CompareIn, progress: Callable) -> dict:
    with slot():
        return _compare(cache, body, progress)


def _compare(cache: DataCache, body: CompareIn, progress: Callable) -> dict:
    pa = ensure_profile(cache, body.a, _sub(progress, 0.0, 0.35))
    pb = ensure_profile(cache, body.b, _sub(progress, 0.35, 0.7))
    result = {"a": body.a, "b": body.b, **compare.compare_profiles(pa, pb)}
    qa, qb = cache.prepare(body.a), cache.prepare(body.b)
    if body.segment:
        progress(0.75, f"分组影响：{body.segment}")
        result["segment"] = compare.segment_impact(qa, qb, body.segment)
    if body.key:
        progress(0.85, f"按主键对齐：{'、'.join(body.key)}")
        result["key"] = compare.key_diff(qa, qb, body.key)
    return result


def data_router(index: PlatformIndex, jobs: JobManager) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{project_id}/data")

    def open_cache(project_id: str) -> tuple[Project, DataCache]:
        project = get_project(index, project_id)
        return project, DataCache(project)

    def ready(cache: DataCache, rel: str) -> Path:
        try:
            parquet = cache.parquet_if_ready(rel)
        except FileNotFoundError:
            raise HTTPException(404, f"文件不存在：{rel}") from None
        except (DataError, ProjectError) as exc:
            raise HTTPException(400, str(exc)) from exc
        if parquet is None:
            raise HTTPException(409, "数据还没准备好：先转换成 Parquet（prepare）")
        return parquet

    def guarded(fn: Callable, *args, **kwargs):
        try:
            with slot():
                return fn(*args, **kwargs)
        except FileNotFoundError as exc:
            raise HTTPException(404, f"文件不存在：{exc}") from None
        except (DataError, ProjectError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("")
    def overview(project_id: str) -> dict:
        project, cache = open_cache(project_id)
        store = DatasetStore(project)
        datasets = store.list()
        registered = {v["path"] for d in datasets for v in d["versions"]}
        files = discover(project.root)
        for f in files:
            f["registered"] = f["path"] in registered
            f["ready"] = cache.parquet_if_ready(f["path"]) is not None
        # 每个文件归到哪个阶段：阶段页只列本阶段的，项目总览只列不属于任何阶段的
        reg, _ = project.load()
        attribute(files, reg, datasets)
        declared = [d.model_dump() for d in project.config.datasets] if project.config else []
        return {
            "readonly": project.readonly,
            "files": files,
            "datasets": datasets,
            "declared": declared,
            "chain": store.chain(),
            "stages": [{"id": s, "label": STAGE_LABEL[s]} for s in STAGE_ORDER],
        }

    @router.get("/lineage")
    def lineage(project_id: str) -> dict:
        project, _ = open_cache(project_id)
        return DatasetStore(project).lineage()

    @router.get("/steps/{step_id}/tables")
    def step_tables(project_id: str, step_id: str, rev: str | None = None) -> dict:
        """一个步骤碰的全部数据表：输入 → 产出、核对过的表、本轮留下的数据文件。"""
        project, _ = open_cache(project_id)
        reg, _ = project.load()
        if reg is None:
            raise HTTPException(409, "这个项目的登记信息读不出来，先修复校验问题")
        try:
            return steptables.step_tables(project, reg, step_id, rev)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None

    @router.get("/steps/{step_id}/stock")
    def step_stock(project_id: str, step_id: str, rev: str | None = None) -> dict:
        """数据层的存量账：原存量 → 增减量（新增 / 更新 / 退出、核对过的表、其他产物）→ 后存量。"""
        from ..data.stock import step_stock as compute

        project, _ = open_cache(project_id)
        reg, _ = project.load()
        if reg is None:
            raise HTTPException(409, "这个项目的登记信息读不出来，先修复校验问题")
        try:
            return compute(project, reg, step_id, rev)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None

    @router.post("/datasets", status_code=201)
    def register(project_id: str, body: RegisterIn) -> dict:
        project, _ = open_cache(project_id)
        return guarded(DatasetStore(project).register, body.path, body.name, body.stage, body.parents,
                       body.produced_by, body.description, body.replaces)

    @router.get("/meta")
    def meta(project_id: str, path: str) -> dict:
        _, cache = open_cache(project_id)
        parquet = guarded(cache.parquet_if_ready, path)
        out = {"path": path, "ready": parquet is not None, "conversion": guarded(cache.conversion_meta, path)}
        if parquet is not None:
            out.update(columns=browse.describe(parquet), rows=browse.row_count(parquet),
                       has_profile=cache.cached_profile(path) is not None)
        return out

    @router.post("/prepare")
    def prepare(project_id: str, body: PathIn) -> dict:
        _, cache = open_cache(project_id)
        guarded(cache.source, body.path)
        return jobs.submit(f"{project_id}:prepare:{body.path}", "prepare", _prepare_job, cache, body.path)

    @router.get("/table")
    def table(project_id: str, path: str, offset: int = 0, limit: int = 200, sort: str | None = None,
              desc: bool = False, filters: str | None = Query(None, description="JSON 数组")) -> dict:
        _, cache = open_cache(project_id)
        parquet = ready(cache, path)
        try:
            parsed = json.loads(filters) if filters else None
        except json.JSONDecodeError:
            raise HTTPException(400, "filters 不是合法 JSON") from None
        return guarded(browse.page, parquet, offset, limit, sort, desc, parsed)

    @router.get("/peek")
    def peek(project_id: str, path: str, columns: str | None = Query(None, description="逗号分隔；不写取前几列"),
             limit: int = 5, sheet: int = 0) -> dict:
        """讲解旁边的数据视图：只取前几行几列，不建缓存、不整表转换，所以每一步都配得起。"""
        project, _ = open_cache(project_id)
        return guarded(peek_data.peek, project, path, [c for c in (columns or "").split(",") if c], limit, sheet)

    @router.get("/sample")
    def sample(project_id: str, path: str, n: int = 200, seed: int = 42) -> dict:
        _, cache = open_cache(project_id)
        return guarded(browse.sample, ready(cache, path), n, seed)

    @router.post("/sql")
    def sql(project_id: str, body: SqlIn) -> dict:
        _, cache = open_cache(project_id)
        return guarded(browse.run_sql, ready(cache, body.path), body.sql)

    @router.get("/profile")
    def get_profile(project_id: str, path: str) -> dict:
        _, cache = open_cache(project_id)
        cached = guarded(cache.cached_profile, path)
        if cached is None:
            raise HTTPException(404, "还没有画像")
        return cached

    @router.post("/profile")
    def make_profile(project_id: str, body: PathIn) -> dict:
        _, cache = open_cache(project_id)
        guarded(cache.source, body.path)
        return jobs.submit(f"{project_id}:profile:{body.path}", "profile", _profile_job, cache, body.path)

    @router.post("/compare")
    def make_compare(project_id: str, body: CompareIn) -> dict:
        _, cache = open_cache(project_id)
        guarded(cache.source, body.a)
        guarded(cache.source, body.b)
        key = f"{project_id}:compare:{body.a}|{body.b}|{','.join(body.key)}|{body.segment}"
        return jobs.submit(key, "compare", _compare_job, cache, body)

    @router.post("/distribution")
    def distribution(project_id: str, body: DistributionIn) -> dict:
        _, cache = open_cache(project_id)
        return guarded(compare.distribution, ready(cache, body.a), ready(cache, body.b), body.column)

    @router.post("/steps/{step_id}/column-notes")
    def column_notes(project_id: str, step_id: str, body: ColumnsIn) -> dict:
        """这几列在讲解与 notebook 里的出处：哪一段说过它、哪一格的代码动了它。界面据此让列名可以点开、跳讲解。"""
        from ..explain.columns import column_notes as compute
        from ..explain.guide import find_step, pick_revision

        project = get_project(index, project_id)
        reg, _ = project.load()
        if reg is None:
            raise HTTPException(409, "这个项目的登记信息读不出来，先修复校验问题")
        try:
            step = find_step(reg, step_id)
            rev = pick_revision(step, body.rev)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        return {"step": step.id, "revision": rev.id, "notes": compute(project, step, rev, body.columns[:60])}

    @router.post("/checks")
    def checks(project_id: str, body: ChecksIn) -> list[dict]:
        _, cache = open_cache(project_id)
        return guarded(invariants.run_checks, ready(cache, body.a), ready(cache, body.b), body.checks)

    return router


def jobs_router(jobs: JobManager) -> APIRouter:
    router = APIRouter()

    @router.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "任务不存在（服务重启后任务记录会清空）")
        return job

    return router


__all__ = ["data_router", "jobs_router", "QueryError"]
