"""路由共用的依赖：按 id 打开已登记项目，错误统一转成 HTTP 状态码。"""

from __future__ import annotations

from fastapi import HTTPException

from ..core.project import Project, ProjectError
from ..index.db import PlatformIndex


def get_project(index: PlatformIndex, project_id: str) -> Project:
    try:
        return index.open_project(project_id)
    except KeyError:
        raise HTTPException(404, "项目未登记") from None
    except ProjectError as exc:
        raise HTTPException(409, str(exc)) from exc
