"""notebook 导读 API：步骤页「讲解」读它。只读，不提供写入（导读由 agent 用 dsflow guide 写）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..explain.guide import guide_view
from ..index.db import PlatformIndex
from .deps import get_project


def guide_router(index: PlatformIndex) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{project_id}")

    @router.get("/steps/{step_id}/guide")
    def guide(project_id: str, step_id: str, rev: str | None = None) -> dict:
        project = get_project(index, project_id)
        reg, _ = project.load()
        if reg is None:
            raise HTTPException(409, "这个项目的登记信息读不出来，先修复校验问题")
        try:
            return guide_view(project, reg, step_id, rev)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None

    return router
