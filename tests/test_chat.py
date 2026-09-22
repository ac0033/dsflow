"""终端客户端：模型配置、消息格式转换、带工具的对话循环（假后端）、斜杠命令、纯文本模式、TUI 能启动。"""

import json

import pytest
from typer.testing import CliRunner

from dsflow.chat import llm
from dsflow.chat.agent import ChatSession, project_info, system_prompt
from dsflow.chat.commands import ChatState, handle
from dsflow.chat.config import PRESETS, ModelConfig, ModelConfigError, ModelEntry
from dsflow.chat.llm import ToolCall, Turn, tool_specs
from dsflow.cli import app as cli
from dsflow.protocol import REGISTRY

runner = CliRunner()


# ---------- 配置 ----------

def test_model_config_add_use_remove(tmp_path, monkeypatch):
    cfg = ModelConfig(tmp_path / "models.json")
    assert cfg.list() == [] and cfg.active() is None
    e = cfg.add("我的deepseek", preset="deepseek", api_key="sk-1234567890abcdef")
    assert e.provider == "openai" and e.base_url == "https://api.deepseek.com" and e.model == "deepseek-chat"
    assert cfg.active().name == "我的deepseek" and e.masked_key() == "sk-123…cdef"
    c = cfg.add("claude", preset="anthropic", api_key="env:MY_KEY")
    assert c.provider == "anthropic" and c.base_url is None and cfg.active().name == "我的deepseek"
    monkeypatch.setenv("MY_KEY", "from-env")
    assert c.resolve_key() == "from-env" and c.masked_key() == "env:MY_KEY"
    monkeypatch.delenv("MY_KEY")
    assert c.resolve_key() is None
    o = cfg.add("本机", preset="ollama")
    assert o.resolve_key() == "" and o.base_url.startswith("http://127.0.0.1")
    with pytest.raises(ModelConfigError):
        cfg.add("坏", provider="google", model="x")
    with pytest.raises(ModelConfigError):
        cfg.add("没模型", provider="openai", base_url="http://x")
    assert cfg.use("claude").name == "claude" and cfg.active().name == "claude"
    cfg.remove("claude")
    assert cfg.active().name in ("我的deepseek", "本机")
    with pytest.raises(ModelConfigError):
        cfg.get("claude")
    data = json.loads((tmp_path / "models.json").read_text(encoding="utf-8"))
    assert set(data["models"]) == {"我的deepseek", "本机"}


def test_env_fallbacks(monkeypatch):
    e = ModelEntry(name="x", provider="openai", model="m", preset="openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DSFLOW_LLM_API_KEY", raising=False)
    assert e.resolve_key() is None
    monkeypatch.setenv("DSFLOW_LLM_API_KEY", "generic")
    assert e.resolve_key() == "generic"
    monkeypatch.setenv("OPENAI_API_KEY", "specific")
    assert e.resolve_key() == "specific"
    assert all("label" in v and "provider" in v for v in PRESETS.values())


# ---------- 消息格式 ----------

def test_message_conversion_both_backends():
    transcript = [
        {"role": "user", "content": "看看进度"},
        {"role": "assistant", "content": "我先看一下。", "tool_calls": [{"id": "t1", "name": "next", "args": {"project": "abc"}}]},
        {"role": "tool", "id": "t1", "name": "next", "content": "{\"ok\": true}"},
        {"role": "assistant", "content": "在 1.1。", "tool_calls": []},
    ]
    a = llm.to_anthropic_messages(transcript)
    assert [m["role"] for m in a] == ["user", "assistant", "user", "assistant"]
    assert a[1]["content"][1] == {"type": "tool_use", "id": "t1", "name": "next", "input": {"project": "abc"}}
    assert a[2]["content"][0]["type"] == "tool_result" and a[2]["content"][0]["tool_use_id"] == "t1"
    o = llm.to_openai_messages("系统", transcript)
    assert o[0] == {"role": "system", "content": "系统"} and o[2]["tool_calls"][0]["function"]["name"] == "next"
    assert o[3] == {"role": "tool", "tool_call_id": "t1", "content": "{\"ok\": true}"}
    specs = tool_specs()
    assert {t["name"] for t in specs} == set(REGISTRY)
    at = llm.to_anthropic_tools(specs)
    ot = llm.to_openai_tools(specs)
    assert at[0]["input_schema"] == ot[0]["function"]["parameters"] and "project" in ot[2]["function"]["parameters"]["properties"]


# ---------- 对话循环（假后端） ----------

class FakeBackend(llm.Backend):
    """按脚本回合应答：先要求调 next，再总结。"""

    def __init__(self):
        self.calls = []

    def complete(self, system, transcript, tools):
        self.calls.append((system, list(transcript)))
        if not any(m["role"] == "tool" for m in transcript):
            return Turn(text="我先看进度。", tool_calls=[ToolCall("t1", "next", {})], stop="tool")
        last = json.loads(transcript[-1]["content"])
        step = last["data"]["step"]["id"]
        return Turn(text=f"现在在 {step}，处于 {last['data']['phase']}。")


def as_dsflow_project(root):
    (root / "dsflow.yaml").write_text("name: 测试项目\n", encoding="utf-8")
    return root


def test_session_runs_tools_and_injects_project(mini_project):
    root, _ = mini_project
    project = project_info(str(as_dsflow_project(root)))
    assert len(project["id"]) == 10
    events = []
    session = ChatSession(FakeBackend(), project, events.append)
    reply = session.send("看看进度")
    assert reply == "现在在 1.2，处于 plan。"
    kinds = [k for k, _ in events]
    assert kinds == ["text", "tool", "result", "text"]
    assert events[1][1]["args"]["project"] == project["id"] and events[2][1]["ok"] is True
    assert [m["role"] for m in session.transcript] == ["user", "assistant", "tool", "assistant"]
    assert "当前项目：id" in system_prompt(project) and "先调 next" in system_prompt(None)


class ErrorBackend(llm.Backend):
    def complete(self, system, transcript, tools):
        raise llm.LLMError("密钥无效：test")


def test_session_reports_llm_error(mini_project):
    root, _ = mini_project
    events = []
    session = ChatSession(ErrorBackend(), project_info(str(as_dsflow_project(root))), events.append)
    assert session.send("hi") == "" and events[-1][0] == "error" and "密钥无效" in events[-1][1]["message"]
    assert session.transcript == []  # 失败的那句不留在记录里


# ---------- 命令 ----------

def test_commands(tmp_path, mini_project, monkeypatch):
    root, _ = mini_project
    state = ChatState(config=ModelConfig(tmp_path / "models.json"))
    handled, lines = handle("/help", state)
    assert handled and any("/models add" in x for x in lines)
    handled, lines = handle("/models", state)
    assert handled and "还没有配置模型" in lines[0]
    handled, lines = handle("/models add 我的模型 --preset deepseek --api-key sk-abcdefghijklmn --set-active", state)
    assert handled and lines[0].startswith("已保存 我的模型") and "sk-abc" in lines[0]
    handled, lines = handle("/models", state)
    assert lines[0].startswith("* 我的模型")
    handled, lines = handle("/models add 坏 --provider google", state)
    assert handled and "用法" in lines[0]
    handled, lines = handle("/models add 没模型 --provider openai --base-url http://x", state)
    assert handled and "失败" in lines[0]
    as_dsflow_project(root)
    handled, lines = handle(f"/project {root}", state)
    assert handled and lines[0].startswith("已选定项目") and state.project["root"] == str(root)
    handled, lines = handle("/next", state)
    assert handled and "1.2" in lines[0] and "plan" in lines[0]
    handled, lines = handle("/nope", state)
    assert handled and "不认识" in lines[0]
    handled, lines = handle("你好", state)
    assert not handled
    handled, lines = handle("/quit", state)
    assert lines == ["__QUIT__"]


def test_plain_mode_with_fake_backend(tmp_path, mini_project, capsys, monkeypatch):
    from dsflow.chat import plain

    root, _ = mini_project
    state = ChatState(config=ModelConfig(tmp_path / "models.json"))
    state.project = project_info(str(as_dsflow_project(root)))
    state.session = ChatSession(FakeBackend(), state.project)
    state.entry = ModelEntry(name="假", provider="openai", model="fake")
    plain.run_plain(state, lines=["/next", "看看进度", "/quit"])
    out = capsys.readouterr().out
    assert "处于：plan" in out and "→ 调用 next" in out and "agent  现在在 1.2" in out


def test_cli_models_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("DSFLOW_HOME", str(tmp_path / "home"))
    r = runner.invoke(cli, ["models", "add", "q", "--preset", "qwen", "--api-key", "sk-xxxxxxxxxxxxxx"])
    assert r.exit_code == 0 and "已保存 q" in r.output
    r = runner.invoke(cli, ["models", "list"])
    assert r.exit_code == 0 and "* q" in r.output and "dashscope" in r.output
    assert runner.invoke(cli, ["models", "use", "nope"]).exit_code == 1
    assert runner.invoke(cli, ["models", "remove", "q"]).exit_code == 0
    assert "还没有配置模型" in runner.invoke(cli, ["models", "list"]).output


def test_tui_starts_and_handles_commands(tmp_path):
    import asyncio

    from dsflow.chat.tui import ChatApp

    state = ChatState(config=ModelConfig(tmp_path / "models.json"))
    app = ChatApp(state)

    async def drive():
        async with app.run_test() as pilot:
            await pilot.press(*"/help", "enter")
            await pilot.pause()
            log = app.query_one("#log")
            return [str(line) for line in log.lines]

    lines = asyncio.run(drive())
    assert any("/models add" in line for line in lines)


def test_model_config_survives_empty_or_corrupt_file(tmp_path):
    path = tmp_path / "models.json"
    path.write_text("", encoding="utf-8")
    cfg = ModelConfig(path)
    assert cfg.list() == [] and cfg.active() is None
    path.write_text("{not json", encoding="utf-8")
    cfg = ModelConfig(path)
    assert cfg.list() == [] and (tmp_path / "models.json.bad").is_file() and "不是合法 JSON" in cfg.last_warning
    e = cfg.add("试\udc95", preset="ollama")  # 管道进来的代理字符不能让写文件崩
    assert "\udc95" not in e.name and json.loads(path.read_text(encoding="utf-8"))["models"]
    assert not list(tmp_path.glob("models.json.tmp*"))
