"""dsflow attach / init 接入：CLAUDE.md、AGENTS.md、skill、hook、登记为可写；hook 入口对导读体检。"""

import json
import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

from dsflow.attach import attach, command_prefix, install_hook
from dsflow.cli import app as cli
from dsflow.core.project import ProjectError, project_id_for
from dsflow.hooks import HOOK_MARKER, guide_lint, hook_command
from dsflow.index.db import PlatformIndex

runner = CliRunner()


def test_init_attaches_everything(tmp_path):
    target = tmp_path / "new"
    result = runner.invoke(cli, ["init", str(target), "--name", "新项目", "--no-venv"])
    assert result.exit_code == 0, result.output
    for rel in ("AGENTS.md", "CLAUDE.md", ".claude/skills/dsflow-project/SKILL.md", ".claude/settings.json"):
        assert (target / rel).is_file(), rel
    assert (target / "CLAUDE.md").read_text(encoding="utf-8").startswith("@AGENTS.md")
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "__DSFLOW__" not in agents and "-m dsflow next ." in agents  # 测试进程的解释器不在项目里 → 绝对路径
    skill = (target / ".claude/skills/dsflow-project/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: dsflow-project") and "__DSFLOW__" not in skill
    settings = json.loads((target / ".claude/settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]["PostToolUse"]
    assert len(hooks) == 1 and hooks[0]["matcher"] == "Write|Edit"
    assert hooks[0]["hooks"][0]["command"] == hook_command(Path(sys.executable))
    row = PlatformIndex().get_project(project_id_for(target))
    assert row and row["readonly"] == 0


def test_init_without_attach_leaves_plain_commands(tmp_path):
    target = tmp_path / "plain"
    assert runner.invoke(cli, ["init", str(target), "--name", "裸项目", "--no-attach", "--no-venv"]).exit_code == 0
    assert not (target / ".claude/settings.json").exists()
    assert "__DSFLOW__" not in (target / "AGENTS.md").read_text(encoding="utf-8")
    assert PlatformIndex().get_project(project_id_for(target)) is None


def test_attach_is_idempotent_and_respects_existing_files(tmp_path):
    target = tmp_path / "p"
    runner.invoke(cli, ["init", str(target), "--name", "项目", "--no-attach", "--no-venv"])
    (target / "AGENTS.md").write_text("# 我自己的规则\n", encoding="utf-8")
    (target / "CLAUDE.md").unlink()  # 模板已经带了 CLAUDE.md；删掉一份看 attach 会补
    first = attach(target)
    assert any("AGENTS.md 已有，未覆盖" in x for x in first) and any("已写 CLAUDE.md" in x for x in first)
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# 我自己的规则\n"
    second = attach(target)
    assert any("hook 已装好，未改动" in x for x in second)
    settings = json.loads((target / ".claude/settings.json").read_text(encoding="utf-8"))
    assert len(settings["hooks"]["PostToolUse"]) == 1
    forced = attach(target, force=True)
    assert any("已写 AGENTS.md" in x for x in forced)
    assert "DSFlow 被管项目" in (target / "AGENTS.md").read_text(encoding="utf-8")


def test_attach_merges_into_existing_settings_and_refuses_readonly(tmp_path):
    target = tmp_path / "p"
    runner.invoke(cli, ["init", str(target), "--name", "项目", "--no-attach", "--no-venv"])
    settings = target / ".claude" / "settings.json"
    settings.parent.mkdir(exist_ok=True)
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(uv run *)"]},
                                    "hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}]}}),
                        encoding="utf-8")
    assert "已装导读体检 hook" in install_hook(settings, Path(sys.executable), force=False)
    merged = json.loads(settings.read_text(encoding="utf-8"))
    assert merged["permissions"]["allow"] == ["Bash(uv run *)"] and len(merged["hooks"]["PostToolUse"]) == 2
    other = tmp_path / "py" / "python.exe"
    other.parent.mkdir()
    other.write_text("")
    assert "命令不同" in install_hook(settings, other, force=False)
    assert install_hook(settings, other, force=True) == "hook 命令已更新"
    assert HOOK_MARKER in json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PostToolUse"][1]["hooks"][0]["command"]

    PlatformIndex().add_project(target, readonly=True)
    try:
        attach(target)
    except ProjectError as exc:
        assert "只读" in str(exc)
    else:
        raise AssertionError("只读项目不该被接入")
    assert any("已登记为可写" in x for x in attach(target, force=True))


def test_command_prefix(tmp_path):
    root = tmp_path / "proj"
    assert command_prefix(root, root / ".venv" / "Scripts" / "python.exe") == "uv run dsflow"
    outside = tmp_path / "other" / "python.exe"
    assert command_prefix(root, outside).endswith('-X utf8 -m dsflow') and outside.as_posix() in command_prefix(root, outside)


def test_attach_needs_project(tmp_path):
    result = runner.invoke(cli, ["attach", str(tmp_path)])
    assert result.exit_code == 1 and "dsflow init" in result.output


def test_hook_guide_lint_blocks_bad_guide_and_ignores_others(mini_project):
    root, _ = mini_project
    from .conftest import REV_11

    guide = root / REV_11 / "guide.yaml"
    (root / "dsflow.yaml").write_text("name: 测试项目\n", encoding="utf-8")  # hook 靠它认出项目目录
    assert guide_lint({"tool_input": {"file_path": str(root / "notes.md")}}) == (0, "")
    assert guide_lint({"tool_input": {}}) == (0, "")
    bad = {"step": "1.1", "brief": {"question": "数据对不对", "answer": "先把表和清单对上"}}
    guide.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    code, message = guide_lint({"tool_input": {"file_path": str(guide)}})
    assert code == 2 and "对上" in message and "1.1 r02" in message
    result = runner.invoke(cli, ["hook", "guide-lint"], input=json.dumps({"tool_input": {"file_path": str(guide)}}))
    assert result.exit_code == 2
    assert runner.invoke(cli, ["hook", "guide-lint"], input="not json").exit_code == 0


def test_guide_lint_thresholds_from_config(mini_project):
    root, _ = mini_project
    from dsflow.core.project import Project
    from dsflow.explain.lint import check_length, thresholds

    (root / "dsflow.yaml").write_text("name: 阈值\nguide_lint:\n  limits: {background: 5}\n", encoding="utf-8")
    th = thresholds(Project(root))
    assert th["limits"]["background"] == 5 and th["limits"]["question"] == 70
    guide = {"brief": {"background": "这一段有超过五个字。", "question": "问", "answer": "答。", "did": "做。", "next": "下。"}}
    assert any("背景" in i.where for i in check_length(guide, th)) and not any("背景" in i.where for i in check_length(guide))
