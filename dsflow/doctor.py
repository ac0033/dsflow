"""`dsflow doctor`：一条命令看清安装、平台目录、登记的项目、当前目录的接入情况，每一条都带修法。"""

from __future__ import annotations

import json
import shutil
import socket
import sys
from pathlib import Path

from . import __version__
from .paths import IN_REPO, cli_prefix, dsflow_home, templates_dir, web_dist


def _check(name: str, ok: bool | None, detail: str, fix: str = "") -> dict:
    status = "ok" if ok else ("warn" if ok is None else "fail")
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _health(port: int) -> dict | None:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def run_doctor(path: Path | str = ".", port: int = 8790) -> dict:
    checks: list[dict] = []
    P = cli_prefix()
    checks.append(_check("dsflow", True, f"v{__version__}，{'仓库形态（uv sync）' if IN_REPO else '安装包形态'}，Python {sys.version.split()[0]}"))
    checks.append(_check("模板", templates_dir().is_dir(), str(templates_dir()), "重新安装 dsflow（安装包缺少 _data/templates）"))
    web = web_dist() / "index.html"
    checks.append(_check("网页", web.is_file(), str(web) if web.is_file() else f"{web} 不存在",
                         "仓库形态：npm --prefix web install && npm --prefix web run build；安装包形态：先在仓库构建网页再重新 uv tool install"))
    try:
        import mcp  # noqa: F401

        checks.append(_check("MCP", True, "mcp 包已装，dsflow mcp 与 /mcp 可用"))
    except ImportError:
        checks.append(_check("MCP", None, "mcp 包未装：只有命令行与 HTTP 两种传输", "仓库形态：uv sync --extra mcp --extra chat；安装包形态：uv tool install \".[mcp,chat]\""))
    home = dsflow_home()
    try:
        probe = home / ".doctor_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        checks.append(_check("平台目录", True, str(home)))
    except OSError as exc:
        checks.append(_check("平台目录", False, f"{home} 不可写：{exc}", "设置环境变量 DSFLOW_HOME 指向一个可写目录"))

    from .index.db import PlatformIndex

    rows = PlatformIndex().list_projects()
    missing = [r for r in rows if not Path(r["root"]).is_dir()]
    checks.append(_check("登记的项目", not missing, f"{len(rows)} 个" + (f"，{len(missing)} 个目录已不存在：{'、'.join(r['name'] for r in missing)}" if missing else ""),
                         f"{P} remove <id> 注销不存在的项目"))

    health = _health(port) if _port_in_use(port) else None
    if health:
        checks.append(_check("平台服务", True, f"http://127.0.0.1:{port} 在运行（v{health.get('version')}）"))
    elif _port_in_use(port):
        checks.append(_check("平台服务", False, f"端口 {port} 被别的程序占用", f"{P} ui --port <别的端口>"))
    else:
        checks.append(_check("平台服务", None, f"没有在 {port} 端口运行", f"{P} ui"))

    for exe, why in (("uv", "运行被管项目的 notebook（uv run）"), ("claude", "Claude Code"), ("git", "版本快照")):
        checks.append(_check(exe, True if shutil.which(exe) else None, shutil.which(exe) or f"PATH 上没有 {exe}（{why}）", ""))

    root = Path(path).resolve()
    if (root / "dsflow.yaml").is_file():
        checks.append(_check("当前目录", True, f"是 DSFlow 项目：{root}"))
        for rel in ("AGENTS.md", "CLAUDE.md", ".claude/skills/dsflow-project/SKILL.md", ".claude/settings.json"):
            fix = f"{P} attach ."
            checks.append(_check(f"接入 · {rel}", (root / rel).is_file(), "有" if (root / rel).is_file() else "没有", fix))
        mcp_json = root / ".mcp.json"
        has = mcp_json.is_file() and "dsflow" in json.loads(mcp_json.read_text(encoding="utf-8")).get("mcpServers", {})
        checks.append(_check("接入 · .mcp.json", True if has else None, "有 dsflow 条目" if has else "没有（MCP agent 才需要）", f"{P} attach . --mcp"))
        from .core.project import project_id_for

        row = PlatformIndex().get_project(project_id_for(root))
        # 只读接入的项目里 agent 不执行代码，缺环境只提示；可写项目缺环境就是要修的项。
        from .env import status as env_status

        env, writable = env_status(root), bool(row) and not row["readonly"]
        if env["venv"] and env["dsflow_linked"]:
            checks.append(_check("接入 · 分析环境", True, f"{root / '.venv'}" + (f"，装了 {'、'.join(env['libs'])}" if env["libs"] else "，还没装分析库")))
        elif env["venv"] and env["linked_to"]:
            checks.append(_check("接入 · 分析环境", False if writable else None,
                                 f"{root / '.venv'} 挂的是 {env['linked_to'][0]}，那个目录已经不在了", f"{P} attach . --venv"))
        elif env["venv"]:
            checks.append(_check("接入 · 分析环境", False if writable else None,
                                 f"{root / '.venv'} 在，但里面没有 dsflow：agent 执行 notebook 会报 No module named 'dsflow'", f"{P} attach . --venv"))
        else:
            checks.append(_check("接入 · 分析环境", False if writable else None,
                                 "项目里没有 .venv：agent 执行代码会用平台自己的解释器，那里没有 pandas", f"{P} attach . --venv"))
        checks.append(_check("接入 · 登记", bool(row) and not row["readonly"], "可写项目" if row and not row["readonly"] else ("只读接入" if row else "未登记"),
                             f"{P} attach ." if not row else f"{P} attach . --force"))
    else:
        checks.append(_check("当前目录", None, f"{root} 不是 DSFlow 项目", f"新项目 {P} init <目录> --name 名称；已有项目先补 dsflow.yaml 再 {P} attach"))

    failed = [c for c in checks if c["status"] == "fail"]
    warned = [c for c in checks if c["status"] == "warn"]
    summary = "全部正常" if not failed and not warned else f"{len(failed)} 项要修，{len(warned)} 项提示"
    return {"checks": checks, "failed": len(failed), "warned": len(warned), "summary": summary}
