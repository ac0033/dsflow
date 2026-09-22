"""DSFlow 后端 API。只绑定 127.0.0.1；对只读项目只做读取。"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..core.lifecycle import build_graph
from ..explain.guide import attach_briefs
from ..core.project import Project, ProjectError
from ..core.steps import step_detail
from ..index.db import PlatformIndex
from ..jobs import JobManager
from ..paths import web_dist
from ..tracking.store import RunStore
from .approval_routes import approval_router
from .ask_routes import ask_router
from .data_routes import data_router, jobs_router
from .guide_routes import guide_router
from .model_routes import model_router
from .progress_routes import progress_router
from .run_routes import run_router
from .deps import get_project

WEB_DIST = web_dist()
LOOPBACK = ("127.0.0.1", "::1", "localhost")


class ProjectIn(BaseModel):
    path: str
    readonly: bool = True


def _mcp_app(host: str):
    """把协议工具挂成 MCP 的 streamable HTTP 子应用；没装 mcp 包就返回 None。"""
    try:
        from mcp.server.transport_security import TransportSecuritySettings

        from ..mcp_server import build_server
    except ImportError:
        return None, None
    server = build_server()
    if host in LOOPBACK:
        security = TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                             allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
                                             allowed_origins=["http://127.0.0.1:*", "http://localhost:*"])
    else:
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)  # 非本机访问靠令牌
    sub = server.streamable_http_app(streamable_http_path="/", host=host, transport_security=security)
    return server, sub


class _McpTrailingSlash:
    """把 `/mcp` 当成 `/mcp/`。

    子应用挂在 `/mcp` 上，少了结尾斜杠时 POST 会得到 405，而文档、各家 agent 的配置里写的都是不带斜杠的
    `http://<平台>:8790/mcp`。这里在路由之前补上斜杠，两种写法都能用。纯 ASGI 中间件，不碰 SSE 的流式响应。
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.app(scope, receive, send)


def create_app(index: PlatformIndex | None = None, jobs: JobManager | None = None,
               token: str | None = None, mcp_host: str = "127.0.0.1", mcp: bool = True) -> FastAPI:
    """平台应用：网页 + HTTP API + /mcp。token 设了以后，非本机来的 /api 与 /mcp 请求都要带 Authorization: Bearer <token>。"""
    from contextlib import asynccontextmanager

    index = index or PlatformIndex()
    jobs = jobs or JobManager()
    server, mcp_sub = _mcp_app(mcp_host) if mcp else (None, None)

    @asynccontextmanager
    async def lifespan(_app):
        if server is not None:
            async with server.session_manager.run():
                yield
        else:
            yield

    app = FastAPI(title="DSFlow", version=__version__, lifespan=lifespan)
    app.state.mcp = mcp_sub is not None
    app.state.token = token

    if token:
        @app.middleware("http")
        async def require_token(request, call_next):
            path = request.url.path
            client = request.client.host if request.client else ""
            if (path.startswith("/api") or path.startswith("/mcp")) and client not in LOOPBACK:
                header = request.headers.get("authorization", "")
                given = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token", "")
                if given != token:
                    from fastapi.responses import JSONResponse

                    return JSONResponse({"ok": False, "protocol": "1", "error": {"code": "forbidden", "message": "需要令牌",
                                         "hint": "请求头 Authorization: Bearer <DSFLOW_TOKEN>"}}, status_code=401)
            return await call_next(request)

    if mcp_sub is not None:
        app.mount("/mcp", mcp_sub, name="mcp")
        app.add_middleware(_McpTrailingSlash)  # 文档与各家配置里写的都是 /mcp，不能只认 /mcp/
    app.include_router(data_router(index, jobs))
    app.include_router(jobs_router(jobs))
    app.include_router(run_router(index))
    app.include_router(progress_router(index))
    app.include_router(model_router(index))
    app.include_router(guide_router(index))
    app.include_router(approval_router(index))
    app.include_router(ask_router(index))

    @app.get("/api/protocol")
    def protocol_doc() -> dict:
        from ..protocol import protocol_document

        return protocol_document()

    @app.post("/api/tools/{name}")
    def call_tool(name: str, args: dict | None = None) -> dict:
        """HTTP 传输：body 就是工具参数；返回协议信封（永远 200，看 ok 字段）。"""
        from ..protocol import call

        return call(name, args or {})

    def open_project(project_id: str) -> Project:
        return get_project(index, project_id)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/projects")
    def list_projects() -> list[dict]:
        return index.list_projects()

    @app.post("/api/projects", status_code=201)
    def add_project(body: ProjectIn) -> dict:
        try:
            return index.add_project(body.path, body.readonly)
        except ProjectError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/projects/{project_id}")
    def remove_project(project_id: str) -> dict:
        if not index.remove_project(project_id):
            raise HTTPException(404, "项目未登记")
        return {"removed": True}

    @app.get("/api/projects/{project_id}")
    def project_detail(project_id: str) -> dict:
        project = open_project(project_id)
        reg, issues = index.reindex(project)
        row = index.get_project(project_id)
        return {
            "project": {**row, "question": project.question},
            "graph": attach_briefs(project, reg, build_graph(reg, project.root, issues, RunStore(project).list())) if reg else None,
            "issues": [i.to_dict() for i in issues],
        }

    @app.get("/api/projects/{project_id}/steps/{step_id}")
    def step(project_id: str, step_id: str) -> dict:
        project = open_project(project_id)
        reg, issues = project.load()
        if reg is None:
            raise HTTPException(409, "这个项目的登记信息读不出来，先修复校验问题")
        try:
            return step_detail(project.root, reg, step_id, issues)
        except KeyError:
            raise HTTPException(404, f"步骤 {step_id} 不存在") from None

    @app.get("/api/projects/{project_id}/file/raw")
    def read_raw(project_id: str, path: str = Query(...)) -> FileResponse:
        project = open_project(project_id)
        try:
            file, media = project.raw_file(path)
        except FileNotFoundError:
            raise HTTPException(404, f"文件不存在：{path}") from None
        except ProjectError as exc:
            raise HTTPException(400, str(exc)) from exc
        # SVG 可能带脚本：禁止执行任何脚本
        return FileResponse(file, media_type=media, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})

    @app.get("/api/projects/{project_id}/validate")
    def validate(project_id: str) -> list[dict]:
        _, issues = index.reindex(open_project(project_id))
        return [i.to_dict() for i in issues]

    @app.get("/api/projects/{project_id}/file")
    def read_file(project_id: str, path: str = Query(..., description="项目内相对路径")) -> dict:
        project = open_project(project_id)
        try:
            return project.read_text(path)
        except FileNotFoundError:
            raise HTTPException(404, f"文件不存在：{path}") from None
        except ProjectError as exc:
            raise HTTPException(400, str(exc)) from exc

    if (WEB_DIST / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(404)
            file = (WEB_DIST / full_path).resolve()
            if full_path and file.is_file() and file.is_relative_to(WEB_DIST.resolve()):
                return FileResponse(file)
            return FileResponse(WEB_DIST / "index.html")

    return app
