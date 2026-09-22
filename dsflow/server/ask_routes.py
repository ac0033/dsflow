"""答疑 API：网页上的对话框问一句，平台流式答一句；问答与标注存平台目录，术语可以一键收进术语表。

提问走 SSE（`text/event-stream`），一行一个事件：tool / result / text / done / error，界面边收边显示。
术语接口单独给出来，执行计划、代码这些没有讲解的页面也能标出行话、悬停看白话解释。
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..ask import models as ask_models
from ..ask.context import Scope
from ..ask.session import AskError, answer, status
from ..ask.store import AskStore
from ..chat.config import ModelConfigError
from ..explain.guide import find_step, load_guide, pick_revision, terms_for
from ..index.db import PlatformIndex
from .deps import get_project

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


class NoteIn(BaseModel):
    """页面上标注的一处：选中的原文 + 用户自己写的一句备注。"""

    quote: str = ""
    note: str = ""


class AskIn(BaseModel):
    question: str
    step: str | None = None
    rev: str | None = None
    tab: str | None = None
    file: str | None = None
    quote: str = ""
    notes: list[NoteIn] = []
    mark: bool = False
    tools: bool = True
    history: list[dict] = []


class TermIn(BaseModel):
    term: str
    meaning: str
    step: str | None = None
    source: str = ""


class MarkIn(BaseModel):
    mark: bool
    step: str | None = None


class ModelIn(BaseModel):
    """网页上填的模型配置：选一家 + 粘密钥就够，模型 ID 与接口地址留空就用这家的默认值。"""

    preset: str
    api_key: str = ""
    name: str = ""
    model: str = ""
    base_url: str = ""


LOOPBACK = ("127.0.0.1", "::1", "localhost")


def _local_only(request: Request) -> None:
    """模型配置里有密钥，只允许平台所在这台机器上的浏览器改；远程 agent 即使带令牌也不行。"""
    client = request.client.host if request.client else ""
    if client not in LOOPBACK:
        raise HTTPException(403, "模型配置只能在平台所在的这台电脑上修改")


def ask_router(index: PlatformIndex) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/ask/status")
    def ask_status() -> dict:
        return status()

    # ---------- 模型配置：在网页上选一家、填密钥、测通 ----------

    @router.get("/ask/models")
    def list_models(request: Request) -> dict:
        _local_only(request)
        return ask_models.listing()

    @router.post("/ask/models")
    def add_model(request: Request, body: ModelIn) -> dict:
        _local_only(request)
        try:
            return ask_models.save(body.preset, body.api_key, body.name, body.model, body.base_url)
        except ModelConfigError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.post("/ask/models/{name}/use")
    def use_model(request: Request, name: str) -> dict:
        _local_only(request)
        try:
            return ask_models.use(name)
        except ModelConfigError as exc:
            raise HTTPException(404, str(exc)) from None

    @router.delete("/ask/models/{name}")
    def drop_model(request: Request, name: str) -> dict:
        _local_only(request)
        try:
            return ask_models.remove(name)
        except ModelConfigError as exc:
            raise HTTPException(404, str(exc)) from None

    @router.post("/ask/models/test")
    def test_model(request: Request, name: str = "") -> dict:
        """真的向模型发一句最短的话，看通不通；密钥错、地址错都在这里一次说清。"""
        _local_only(request)
        return ask_models.test(name)

    @router.get("/projects/{project_id}/terms")
    def project_terms(project_id: str, step: str | None = None, rev: str | None = None) -> dict:
        """术语表：本步登记的 > 项目术语表 > 平台内置。步骤省略时只给后两层。"""
        project = get_project(index, project_id)
        guide = None
        if step:
            reg, _ = project.load()
            if reg is not None:
                try:
                    found = find_step(reg, step)
                    guide, _, _, _ = load_guide(project, found, pick_revision(found, rev))
                except KeyError:
                    guide = None
        return {"terms": terms_for(project, guide)}

    @router.get("/projects/{project_id}/asks")
    def list_asks(project_id: str, step: str | None = None, rev: str | None = None) -> dict:
        project = get_project(index, project_id)
        return {"records": [r.to_dict() for r in AskStore(project).list(step, rev)]}

    @router.delete("/projects/{project_id}/asks/{ask_id}")
    def delete_ask(project_id: str, ask_id: str, step: str | None = None) -> dict:
        project = get_project(index, project_id)
        if not AskStore(project).delete(ask_id, step):
            raise HTTPException(404, "这条问答已经不在了")
        return {"deleted": True}

    @router.patch("/projects/{project_id}/asks/{ask_id}")
    def set_mark(project_id: str, ask_id: str, body: MarkIn) -> dict:
        """钉住 / 取消钉住：钉住的那句话会一直高亮在页面上。"""
        project = get_project(index, project_id)
        record = AskStore(project).update(ask_id, body.step, mark=body.mark)
        if record is None:
            raise HTTPException(404, "这条问答已经不在了")
        return record.to_dict()

    @router.post("/projects/{project_id}/asks/{ask_id}/term")
    def save_term(project_id: str, ask_id: str, body: TermIn) -> dict:
        """把答疑里解释清楚的行话收进术语表（只读项目写平台目录，不碰项目文件）。"""
        from ..protocol import call as protocol_call

        project = get_project(index, project_id)
        env = protocol_call("vocabulary_add", {"project": project.id, "term": body.term, "meaning": body.meaning,
                                               "source": body.source or "平台答疑"})
        if not env.get("ok"):
            raise HTTPException(400, (env.get("error") or {}).get("message", "术语没能登记"))
        AskStore(project).update(ask_id, body.step, saved_term=body.term)
        return env["data"]

    @router.post("/projects/{project_id}/ask")
    def ask(project_id: str, body: AskIn) -> StreamingResponse:
        project = get_project(index, project_id)
        reg, _ = project.load()
        scope = Scope.from_dict(body.model_dump())

        def events() -> Iterator[str]:
            # 钉不钉在页面上，在存档那一刻就定下来（Scope.pinned），这里不再补写：
            # 用户答到一半关掉页面、连接断了，存下来的问答照样带着该钉住的那几句。
            try:
                stream = answer(project, reg, scope, body.question, history=body.history, use_tools=body.tools)
                for event in stream:
                    yield "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"
            except AskError as exc:
                yield "data: " + json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n\n"

        return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)

    return router
