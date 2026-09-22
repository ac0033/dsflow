"""进度与核对 API：看板、告警（含哈希核对）、问题 / 决策 / 待决事项、数字与术语核对、知识边界。"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from ..core.project import Project
from ..core.schemas import Registry
from ..index.db import PlatformIndex
from ..progress.alerts import compute_alerts
from ..progress.board import build_board
from ..progress.checks import load_vocab, project_checks, step_checks
from ..progress.knowledge import knowledge
from ..progress.tracker import TrackerError, TrackerStore, project_pending
from ..tracking.store import RunStore
from .deps import get_project


def progress_router(index: PlatformIndex) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{project_id}")

    def load(project_id: str) -> tuple[Project, Registry, list]:
        project = get_project(index, project_id)
        reg, issues = project.load()
        if reg is None:
            raise HTTPException(409, "这个项目的登记信息读不出来，先修复校验问题")
        return project, reg, issues

    @router.get("/board")
    def board(project_id: str) -> dict:
        project, reg, issues = load(project_id)
        return build_board(project, reg, issues, RunStore(project).list())

    @router.post("/board/verify")
    def verify(project_id: str) -> list[dict]:
        """对大小或修改时间变了的原始数据重新计算哈希，确认内容是否真的变了。"""
        project, reg, issues = load(project_id)
        return compute_alerts(project, reg, issues, RunStore(project).list(), verify=True)

    @router.get("/tracker")
    def tracker(project_id: str) -> dict:
        project, reg, _ = load(project_id)
        store = TrackerStore(project)
        return {**{k: store.list(k) for k in ("issues", "decisions", "pending")},
                "project_pending": project_pending(project.root, reg), "readonly": project.readonly}

    @router.post("/tracker/{kind}", status_code=201)
    def create(project_id: str, kind: str, data: dict = Body(...)) -> dict:
        project, _, _ = load(project_id)
        try:
            return TrackerStore(project).create(kind, data)
        except TrackerError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.patch("/tracker/{kind}/{item_id}")
    def update(project_id: str, kind: str, item_id: str, patch: dict = Body(...)) -> dict:
        project, _, _ = load(project_id)
        try:
            return TrackerStore(project).update(kind, item_id, patch)
        except KeyError:
            raise HTTPException(404, f"{item_id} 不存在") from None
        except TrackerError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.delete("/tracker/{kind}/{item_id}")
    def delete(project_id: str, kind: str, item_id: str) -> dict:
        project, _, _ = load(project_id)
        try:
            removed = TrackerStore(project).delete(kind, item_id)
        except TrackerError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not removed:
            raise HTTPException(404, f"{item_id} 不存在")
        return {"removed": True}

    @router.get("/checks")
    def checks(project_id: str) -> list[dict]:
        project, reg, _ = load(project_id)
        return project_checks(project, reg)

    @router.get("/steps/{step_id}/checks")
    def checks_for_step(project_id: str, step_id: str) -> dict:
        project, reg, _ = load(project_id)
        try:
            return step_checks(project, reg, step_id, load_vocab(project))
        except KeyError:
            raise HTTPException(404, f"步骤 {step_id} 不存在") from None

    @router.get("/knowledge")
    def knowledge_view(project_id: str) -> dict:
        project, reg, _ = load(project_id)
        pending = [*TrackerStore(project).list("pending"), *project_pending(project.root, reg)]
        goals = project.config.metric_goals if project.config else {}
        return knowledge(project, reg, RunStore(project).list(), pending, goals)

    return router
