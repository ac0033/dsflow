"""MCP 传输与插件：服务暴露协议里的全部工具、调用返回信封、attach --mcp 写 .mcp.json、插件目录的文件合法。"""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dsflow.attach import attach
from dsflow.cli import app as cli
from dsflow.paths import REPO_ROOT
from dsflow.protocol import REGISTRY

runner = CliRunner()


def test_server_exposes_registry_and_returns_envelopes(mini_project):
    pytest.importorskip("mcp.server.mcpserver")
    from dsflow.mcp_server import build_server

    root, _ = mini_project
    server = build_server()
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert set(tools) == set(REGISTRY)
    assert "project" in tools["next"].input_schema["properties"] and "step" in tools["next"].input_schema["properties"]
    assert tools["file_write"].description.startswith("写项目里的文件")
    env = envelope(asyncio.run(server.call_tool("steps_list", {"project": str(root)})))
    assert env["ok"] and env["protocol"] == "1" and [s["id"] for s in env["data"]] == ["1.1", "1.2", "2.1"]
    env = envelope(asyncio.run(server.call_tool("file_read", {"project": str(root), "path": "nope.md"})))
    assert env["ok"] is False and env["error"]["code"] == "not_found"


def envelope(result):
    """CallToolResult → 信封：优先 structured_content，否则解析第一段文本。"""
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and "ok" in structured:
        return structured
    content = getattr(result, "content", None) or (result[0] if isinstance(result, tuple) else result)
    return json.loads(content[0].text)


def test_attach_mcp_writes_config(tmp_path):
    target = tmp_path / "p"
    assert runner.invoke(cli, ["init", str(target), "--name", "项目", "--no-attach", "--no-venv"]).exit_code == 0
    lines = attach(target, mcp=True)
    assert any(".mcp.json" in x for x in lines)
    cfg = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    entry = cfg["mcpServers"]["dsflow"]
    assert entry["command"] == Path(sys.executable).resolve().as_posix() and entry["args"][-2:] == ["dsflow", "mcp"]
    (target / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    attach(target, mcp=True)
    cfg = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))
    assert set(cfg["mcpServers"]) == {"other", "dsflow"}
    assert any("未改动" in x for x in attach(target, mcp=True))


def test_plugin_files_are_valid():
    plugin = REPO_ROOT / "plugin"
    manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "dsflow" and manifest["version"]
    hooks = json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    cmd = hooks["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    assert "dsflow hook guide-lint" in cmd and "${CLAUDE_PLUGIN_ROOT}" in cmd
    mcp = json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["dsflow"]["args"][-2:] == ["dsflow", "mcp"]
    skill = (plugin / "skills" / "dsflow-project" / "SKILL.md").read_text(encoding="utf-8")
    canonical = (REPO_ROOT / "skills" / "dsflow-project" / "SKILL.md").read_text(encoding="utf-8")
    template = (REPO_ROOT / "templates" / "project" / ".claude" / "skills" / "dsflow-project" / "SKILL.md").read_text(encoding="utf-8")
    assert skill == canonical == template, "接口 skill 三处必须完全一致（源在 skills/dsflow-project）"
    assert skill.startswith("---\nname: dsflow-project")
