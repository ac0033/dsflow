"""`dsflow attach`：把一个项目接进平台，一次装齐 agent 要的东西。

装什么：AGENTS.md（跨 agent 的工作规则）、CLAUDE.md（一行 `@AGENTS.md`，Claude Code 只读它）、
.claude/skills/dsflow-project/SKILL.md（Claude Code 在项目里自动发现的 skill）、
.claude/settings.json 里的导读体检 hook，最后把项目登记为可写。幂等：已有的文件不覆盖，--force 才覆盖。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from .core.project import ProjectError, project_id_for
from .hooks import HOOK_MARKER, hook_command
from .index.db import PlatformIndex
from .paths import IN_REPO, templates_dir

TEMPLATE = templates_dir() / "project"
INSTALL = ("AGENTS.md", "CLAUDE.md", ".claude/skills/dsflow-project/SKILL.md")
PLACEHOLDER = "__DSFLOW__"


def command_prefix(root: Path, python: Path) -> str:
    """写进 AGENTS.md / SKILL.md 的命令前缀：项目自己的 .venv 里有 dsflow 就用 uv run，否则用绝对路径的解释器。"""
    python = python.resolve()
    if python.is_relative_to(root):
        return "uv run dsflow"
    if not IN_REPO and shutil.which("dsflow"):
        return "dsflow"  # pip / uv tool 装的包：命令在 PATH 上，任何目录都能直接用
    return f'"{python.as_posix()}" -X utf8 -m dsflow'


def render(template_rel: str, prefix: str) -> str:
    return (TEMPLATE / template_rel).read_text(encoding="utf-8").replace(PLACEHOLDER, prefix)


def install_hook(settings_path: Path, python: Path, force: bool) -> str:
    """在 .claude/settings.json 里合并一条 PostToolUse hook；已有同样的就不重复。"""
    settings: dict = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError as exc:
            raise ProjectError(f"{settings_path} 不是合法 JSON：{exc}") from exc
    post = settings.setdefault("hooks", {}).setdefault("PostToolUse", [])
    command = hook_command(python)
    for entry in post:
        for h in entry.get("hooks", []):
            if HOOK_MARKER in (h.get("command") or ""):
                if h["command"] == command:
                    return "hook 已装好，未改动"
                if not force:
                    return f"hook 已存在但命令不同（{h['command']}），未改动；要换成 {command} 请加 --force"
                h["command"] = command
                settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return "hook 命令已更新"
    post.append({"matcher": "Write|Edit", "hooks": [{"type": "command", "command": command, "timeout": 120}]})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return "已装导读体检 hook（PostToolUse · Write|Edit）"


def install_mcp(path: Path, python: Path, force: bool) -> str:
    """写 .mcp.json：支持 MCP 的 agent（Claude Code、Claude Desktop 等）启动 `python -m dsflow mcp`。"""
    config: dict = {}
    if path.is_file():
        try:
            config = json.loads(path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError as exc:
            raise ProjectError(f"{path} 不是合法 JSON：{exc}") from exc
    servers = config.setdefault("mcpServers", {})
    entry = {"command": Path(python).resolve().as_posix(), "args": ["-X", "utf8", "-m", "dsflow", "mcp"]}
    if "dsflow" in servers and not force:
        return ".mcp.json 里已有 dsflow，未改动（要换解释器加 --force）"
    servers["dsflow"] = entry
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return "已写 .mcp.json（dsflow mcp，stdio）；那个解释器要装了 mcp 包：uv sync --extra mcp"


def attach(project_dir: str | Path, python: str | Path | None = None, force: bool = False,
           register: bool = True, mcp: bool = False) -> list[str]:
    root = Path(project_dir).resolve()
    if not (root / "dsflow.yaml").is_file():
        raise ProjectError(f"{root} 不是 DSFlow 项目（没有 dsflow.yaml）；新项目先用 dsflow init")
    index = PlatformIndex()
    row = index.get_project(project_id_for(root))
    if row and row["readonly"] and not force:
        raise ProjectError("这个项目登记为只读接入，平台不在它的目录里写任何文件。确实要接入就加 --force（会改成可写）")
    py = Path(python) if python else Path(sys.executable)
    prefix = command_prefix(root, py)
    done: list[str] = []
    for rel in INSTALL:
        dest = root / rel
        if dest.exists() and not force:
            done.append(f"{rel} 已有，未覆盖（模板有更新时用 --force）")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render(rel, prefix), encoding="utf-8")
        done.append(f"已写 {rel}")
    done.append(install_hook(root / ".claude" / "settings.json", py, force))
    if mcp:
        done.append(install_mcp(root / ".mcp.json", py, force))
    if register:
        index.add_project(root, readonly=False)
        done.append(f"已登记为可写项目，id={project_id_for(root)}")
    done.append(f"agent 在这个目录里运行命令用：{prefix} …")
    return done
