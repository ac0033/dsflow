"""工作规矩（dsflow/core/rules.py）：每个接口都读得到同一份，缺一个就红。

接口 = 协议文档 / next 的返回 / MCP instructions / 终端客户端的系统提示 / 两个 skill（三份副本）/ 项目里的 AGENTS.md / 面向用户的文档。
"""

import json

from typer.testing import CliRunner

from dsflow.chat.agent import system_prompt
from dsflow.cli import app as cli
from dsflow.core.rules import RULE_TITLES, WORK_RULES, brief, one_line, rules_markdown
from dsflow.paths import REPO_ROOT
from dsflow.protocol import REGISTRY, call, protocol_document

runner = CliRunner()

# 规矩必须逐字出现在这些文件里：改了规矩就要同时改它们，不然这条测试会红。
FILES = (
    "docs/agent-protocol.md",
    "docs/agent-guide.md",
    "docs/接入指南.md",
    "README.md",
    "skills/dsflow-project/SKILL.md",
    "plugin/skills/dsflow-project/SKILL.md",
    "templates/project/.claude/skills/dsflow-project/SKILL.md",
    "skills/data-science-project/SKILL.md",
    "skills/data-science-project/references/workflow.md",
    "templates/project/AGENTS.md",
)


def test_every_document_carries_every_rule():
    assert RULE_TITLES == ("开工前先检查环境", "一步是一个完整独立的单元")
    for rel in FILES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for title in RULE_TITLES:
            assert title in text, f"{rel} 里没有「{title}」"


def test_protocol_document_and_markdown_carry_the_rules():
    doc = protocol_document()
    assert [r["id"] for r in doc["rules"]] == [r["id"] for r in WORK_RULES]
    assert doc["rules"][0]["why"] and doc["rules"][0]["how"]
    md = rules_markdown()
    assert all(r["title"] in md for r in WORK_RULES)
    assert md in (REPO_ROOT / "docs" / "agent-protocol.md").read_text(encoding="utf-8")


def test_cli_and_http_and_mcp_and_chat_all_expose_the_rules(mini_project):
    root, _ = mini_project
    text = runner.invoke(cli, ["protocol"]).output
    as_json = json.loads(runner.invoke(cli, ["protocol", "--format", "json"]).output)
    markdown = runner.invoke(cli, ["protocol", "--format", "markdown"]).output
    for title in RULE_TITLES:
        assert title in text and title in markdown
        assert title in system_prompt(None)
        assert title in one_line()
    assert [r["id"] for r in as_json["rules"]] == [r["id"] for r in WORK_RULES]

    from dsflow.mcp_server import INSTRUCTIONS

    assert all(title in INSTRUCTIONS for title in RULE_TITLES)

    got = call("next", {"project": str(root)})["data"]
    assert got["rules"] == brief() and [r["title"] for r in got["rules"]] == list(RULE_TITLES)


def test_environment_tools_are_registered():
    assert {"env_check", "env_prepare"} <= set(REGISTRY)
    assert REGISTRY["env_check"].group == "环境"


def test_fresh_project_starts_at_preflight_until_the_environment_is_ready(tmp_path, monkeypatch):
    """接入之后、一步都还没登记时：环境没准备好，next 停在 preflight，第一件事是环境自检。"""
    target = tmp_path / "新项目"
    assert runner.invoke(cli, ["init", str(target), "--name", "新项目", "--no-venv"]).exit_code == 0
    got = call("next", {"project": str(target)})["data"]
    assert got["phase"] == "preflight" and got["environment"]["ready"] is False
    assert [c["tool"] for c in got["tool_calls"]][:2] == ["env_check", "env_prepare"]
    assert "--venv" in got["commands"][0]

    # 环境好了就不再出现这个环节：假装快检查通过
    from dsflow.core import next as next_mod

    monkeypatch.setattr(next_mod, "environment", lambda p: {"ready": True, "checked": True, "detail": "已就绪。", "fix": ""})
    after = call("next", {"project": str(target)})["data"]
    assert after["phase"] == "all_done" and after["tool_calls"][0]["tool"] == "step_add"
    assert any("一步是一个完整独立的单元" in line for line in after["todo"])
