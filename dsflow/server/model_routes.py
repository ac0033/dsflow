"""模型与交付 API：模型登记、版本详情（门槛、交付清单核对）、状态变更、生成或刷新交付清单。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core.project import ProjectError
from ..delivery.checklist import check_checklist, draft_checklist, load_checklist, write_checklist
from ..delivery.models import NEXT, ModelError, ModelStore
from ..index.db import PlatformIndex
from .deps import get_project


class RegisterIn(BaseModel):
    path: str
    name: str
    run_id: str | None = None
    description: str = ""


class StatusIn(BaseModel):
    to: str
    note: str = ""


def model_router(index: PlatformIndex) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{project_id}/models")

    def version_of(store: ModelStore, name: str, version: str) -> dict:
        try:
            return store.get(name, version)
        except (KeyError, ModelError):
            raise HTTPException(404, f"模型 {name} 没有版本 {version}") from None

    @router.get("")
    def list_models(project_id: str) -> dict:
        project = get_project(index, project_id)
        return {"models": ModelStore(project).list(), "readonly": project.readonly}

    @router.post("", status_code=201)
    def register(project_id: str, body: RegisterIn) -> dict:
        project = get_project(index, project_id)
        try:
            return ModelStore(project).register(body.path, body.name, body.run_id, body.description)
        except FileNotFoundError:
            raise HTTPException(404, f"文件不存在：{body.path}") from None
        except ModelError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/{name}/{version}")
    def detail(project_id: str, name: str, version: str) -> dict:
        project = get_project(index, project_id)
        store = ModelStore(project)
        v = version_of(store, name, version)
        target = NEXT[v["status"]]
        return {**v, "target": target, "gates": store.gates(v, target), "checklist": check_checklist(project, v),
                "readonly": project.readonly}

    @router.post("/{name}/{version}/status")
    def change_status(project_id: str, name: str, version: str, body: StatusIn) -> dict:
        store = ModelStore(get_project(index, project_id))
        version_of(store, name, version)
        try:
            return store.promote(name, version, body.to, body.note)
        except ModelError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/{name}/{version}/checklist")
    def make_checklist(project_id: str, name: str, version: str) -> dict:
        """生成或刷新交付清单：事实部分按登记与运行记录重写，人写的部分保留。"""
        project = get_project(index, project_id)
        v = version_of(ModelStore(project), name, version)
        existing, error = load_checklist(project, name)
        if error:
            raise HTTPException(409, f"{error}；先修好文件再刷新，平台不覆盖无法解析的清单")
        try:
            write_checklist(project, draft_checklist(project, v, existing))
        except ProjectError as exc:
            raise HTTPException(403, str(exc)) from exc
        return check_checklist(project, v)

    return router
