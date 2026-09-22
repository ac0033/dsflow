"""平台自身的目录约定：两种安装形态。

- 仓库形态（开发者 `uv sync`）：模板在 `<仓库>/templates`，网页在 `<仓库>/web/dist`，平台目录默认 `<仓库>/.dsflow_home`。
- 安装包形态（在仓库目录 `uv tool install ".[mcp,chat]"`；PyPI 上的 dsflow 是别人的包）：模板与网页打进包里的 `dsflow/_data/`，平台目录默认 `~/.dsflow`。

DSFLOW_HOME 存放平台索引（platform.sqlite）以及只读项目的缓存；只读接入的项目目录里绝不写入任何文件。
"""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
IN_REPO = (REPO_ROOT / "pyproject.toml").is_file() and (REPO_ROOT / "templates").is_dir()
DATA_DIR = PACKAGE_DIR / "_data"


def templates_dir() -> Path:
    return REPO_ROOT / "templates" if IN_REPO else DATA_DIR / "templates"


def web_dist() -> Path:
    return REPO_ROOT / "web" / "dist" if IN_REPO else DATA_DIR / "web"


def skills_dir() -> Path:
    return REPO_ROOT / "skills" if IN_REPO else DATA_DIR / "skills"


def cli_prefix() -> str:
    """文档、提示里该怎么写命令：装成工具后是 `dsflow`；在仓库里开发时是 `uv run dsflow`（要在仓库目录运行）。

    在 `uv run` 里跑时，仓库自己的 `.venv/Scripts/dsflow.exe` 也在 PATH 上，但用户自己开的终端里没有它，
    所以这种 dsflow 不算数——只有仓库之外的 dsflow 才说明用户能直接敲。
    """
    import shutil
    import sys

    if not IN_REPO:
        return "dsflow"
    found = shutil.which("dsflow")
    if found and REPO_ROOT not in Path(found).resolve().parents:
        return "dsflow"
    if Path(sys.argv[0] or "").name == "__main__.py":
        return "python -m dsflow"  # 本来就是这么起的（站在源码目录里用 python -m dsflow），照原样告诉用户
    return "uv run dsflow"


def default_home() -> Path:
    return REPO_ROOT / ".dsflow_home" if IN_REPO else Path.home() / ".dsflow"


def dsflow_home() -> Path:
    home = Path(os.environ.get("DSFLOW_HOME") or default_home())
    home.mkdir(parents=True, exist_ok=True)
    return home
