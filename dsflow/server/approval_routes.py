"""审批闭环 API：用户在步骤页点「通过 / 退回 / 确认完成」，平台写 approval_record.md 并改注册表状态。

这是平台唯一会写注册表的路由；只读项目返回 403，状态不对返回 409。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.approval import ApprovalError, approvals_view, decide, withdraw
from ..index.db import PlatformIndex
from .deps import get_project


class Withdrawal(BaseModel):
    note: str = Field("", description="为什么撤回，会原样记进审批记录")
    rev: str | None = None


class Decision(BaseModel):
    kind: str = Field(description="approval 计划审批 / acceptance 完成确认")
    decision: str = Field(description="approve / reject")
    note: str = Field("", description="用户的原话")
    rev: str | None = None


def approval_router(index: PlatformIndex) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{project_id}/steps/{step_id}")

    def load(project_id: str):
        project = get_project(index, project_id)
        reg, _ = project.load()
        if reg is None:
            raise HTTPException(409, "这个项目的登记信息读不出来，先修复校验问题")
        return project, reg

    @router.get("/approval")
    def approvals(project_id: str, step_id: str, rev: str | None = None) -> dict:
        project, reg = load(project_id)
        try:
            return approvals_view(project, reg, step_id, rev)
        except ApprovalError as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @router.post("/approval")
    def post_decision(project_id: str, step_id: str, body: Decision) -> dict:
        project, reg = load(project_id)
        try:
            result = decide(project, reg, step_id, body.kind, body.decision, body.note, source="平台", rev_id=body.rev)
        except ApprovalError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        index.reindex(project)
        return result

    @router.post("/approval/withdraw")
    def post_withdrawal(project_id: str, step_id: str, body: Withdrawal) -> dict:
        """撤回最后一条审批：状态改回去，记录里追加一条「撤回」（记录从不删除）。"""
        project, reg = load(project_id)
        try:
            result = withdraw(project, reg, step_id, body.note, source="平台", rev_id=body.rev)
        except ApprovalError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        index.reindex(project)
        return result

    return router
