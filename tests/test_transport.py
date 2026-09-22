"""传输与安装：/mcp streamable HTTP、令牌、安装形态的路径、doctor。"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dsflow import paths
from dsflow.cli import app as cli
from dsflow.doctor import run_doctor
from dsflow.index.db import PlatformIndex
from dsflow.protocol import REGISTRY
from dsflow.server.app import create_app

runner = CliRunner()
ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _rpc(client, method, params=None, id_=1, session=None, token=None):
    headers = dict(ACCEPT)
    if session:
        headers["mcp-session-id"] = session
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}
    return client.post("/mcp/", json=body, headers=headers)


def _payload(resp):
    text = resp.text
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        text = next(line[5:] for line in text.splitlines() if line.startswith("data:"))
    return json.loads(text)


def test_mcp_over_http_lists_and_calls_tools(mini_project):
    pytest.importorskip("mcp.server.mcpserver")
    root, _ = mini_project
    app = create_app(PlatformIndex(), mcp_host="0.0.0.0")
    assert app.state.mcp is True
    with TestClient(app) as client:
        init = _rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
        assert init.status_code == 200, init.text
        session = init.headers.get("mcp-session-id")
        assert session and _payload(init)["result"]["serverInfo"]["name"] == "dsflow"
        client.post("/mcp/", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={**ACCEPT, "mcp-session-id": session})
        tools = _payload(_rpc(client, "tools/list", id_=2, session=session))["result"]["tools"]
        assert {t["name"] for t in tools} == set(REGISTRY)
        called = _payload(_rpc(client, "tools/call", {"name": "steps_list", "arguments": {"project": str(root)}}, id_=3, session=session))
        env = called["result"].get("structuredContent") or json.loads(called["result"]["content"][0]["text"])
        assert env["ok"] and [s["id"] for s in env["data"]] == ["1.1", "1.2", "2.1"]


def test_mcp_accepts_url_without_trailing_slash(mini_project):
    """文档和各家 agent 配置里写的都是 /mcp；子应用挂在 /mcp 上，少了斜杠会 405。"""
    pytest.importorskip("mcp.server.mcpserver")
    app = create_app(PlatformIndex(), mcp_host="0.0.0.0")
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
    with TestClient(app) as client:
        for url in ("/mcp", "/mcp/"):
            resp = client.post(url, json=body, headers=ACCEPT)
            assert resp.status_code == 200, f"{url} -> {resp.status_code} {resp.text[:200]}"
            assert _payload(resp)["result"]["serverInfo"]["name"] == "dsflow"


def test_token_guards_api_and_mcp_for_non_loopback(mini_project):
    root, _ = mini_project
    app = create_app(PlatformIndex(), token="secret", mcp_host="0.0.0.0", mcp=False)
    with TestClient(app) as client:  # TestClient 的客户端地址是 testclient，不算本机
        r = client.post("/api/tools/steps_list", json={"project": str(root)})
        assert r.status_code == 401 and r.json()["error"]["code"] == "forbidden"
        r = client.post("/api/tools/steps_list", json={"project": str(root)}, headers={"Authorization": "Bearer secret"})
        assert r.status_code == 200 and r.json()["ok"]
        r = client.post("/api/tools/steps_list?token=secret", json={"project": str(root)})
        assert r.status_code == 200
        assert client.get("/api/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
    app = create_app(PlatformIndex(), mcp=False)
    with TestClient(app) as client:  # 没设令牌就不拦
        assert client.get("/api/health").status_code == 200


def test_ui_refuses_public_host_without_token():
    result = runner.invoke(cli, ["ui", "--host", "0.0.0.0", "--no-browser"])
    assert result.exit_code == 1 and "令牌" in result.output


def test_paths_follow_install_layout(monkeypatch, tmp_path):
    assert paths.IN_REPO and paths.templates_dir() == paths.REPO_ROOT / "templates"
    monkeypatch.setattr(paths, "IN_REPO", False)
    assert paths.templates_dir() == paths.DATA_DIR / "templates" and paths.web_dist() == paths.DATA_DIR / "web"
    assert paths.default_home().name == ".dsflow"
    monkeypatch.setenv("DSFLOW_HOME", str(tmp_path / "h"))
    assert paths.dsflow_home() == tmp_path / "h"


def test_cli_prefix_matches_how_dsflow_was_started(monkeypatch):
    """打印给用户的命令前缀要跟他真能敲的一致：uv run 里的 dsflow.exe 在用户终端里没有。"""
    import shutil
    import sys

    monkeypatch.setattr(paths, "IN_REPO", True)
    monkeypatch.setattr(shutil, "which", lambda name: str(paths.REPO_ROOT / ".venv" / "Scripts" / "dsflow.exe"))
    monkeypatch.setattr(sys, "argv", ["dsflow"])
    assert paths.cli_prefix() == "uv run dsflow"
    monkeypatch.setattr(sys, "argv", [str(paths.PACKAGE_DIR / "__main__.py")])
    assert paths.cli_prefix() == "python -m dsflow"
    monkeypatch.setattr(shutil, "which", lambda name: str(Path.home() / ".local" / "bin" / "dsflow.exe"))
    assert paths.cli_prefix() == "dsflow"
    monkeypatch.setattr(paths, "IN_REPO", False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert paths.cli_prefix() == "dsflow"


def test_doctor_reports_project_attachment(tmp_path):
    report = run_doctor(tmp_path)
    names = {c["name"]: c for c in report["checks"]}
    assert names["dsflow"]["status"] == "ok" and names["当前目录"]["status"] == "warn"
    target = tmp_path / "p"
    assert runner.invoke(cli, ["init", str(target), "--name", "项目", "--no-venv"]).exit_code == 0
    report = run_doctor(target)
    names = {c["name"]: c for c in report["checks"]}
    assert names["当前目录"]["status"] == "ok" and names["接入 · AGENTS.md"]["status"] == "ok"
    assert names["接入 · 登记"]["status"] == "ok" and names["接入 · .mcp.json"]["status"] == "warn"
    # --no-venv 建的项目没有分析环境，doctor 要把它算成"要修"，并给出补的办法
    assert names["接入 · 分析环境"]["status"] == "fail" and report["failed"] == 1
    from dsflow import env as envmod

    list(envmod.prepare(target, libs=(), seed=False))
    result = runner.invoke(cli, ["doctor", str(target), "--json"])
    assert result.exit_code == 0 and json.loads(result.output)["failed"] == 0
    text = runner.invoke(cli, ["doctor", str(target)]).output
    assert "✓ dsflow" in text and "修法" in text
