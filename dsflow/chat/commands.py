"""斜杠命令：TUI 和纯文本模式共用。`/help` 列出全部。"""

from __future__ import annotations

import argparse
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field

from ..core.project import ProjectError
from ..protocol import call
from .agent import ChatSession, project_info
from .config import PRESETS, ModelConfig, ModelConfigError, ModelEntry
from .llm import LLMError, make_backend

HELP = """命令：
  /models                      列出配好的模型（* 为当前）
  /models add <名称> [--preset anthropic|openai|deepseek|qwen|moonshot|zhipu|openrouter|ollama]
                    [--provider anthropic|openai] [--base-url <地址>] [--model <模型 ID>]
                    [--api-key <密钥 或 env:变量名>] [--set-active]
  /models use <名称>            切换当前模型（/model <名称> 同义）
  /models remove <名称>         删除
  /models status               用当前模型发一句话，测通不通
  /project <目录或 id>          选定要推进的项目（未登记的目录会顺手登记）
  /next                        看项目在哪一步、缺什么、下一步做什么
  /clear                       清空对话记录
  /quit                        退出
不带斜杠的内容直接发给模型；它会先调 next，再按 tool_calls 推进，交完计划会停下来等你在网页或这里审批。"""


@dataclass
class ChatState:
    config: ModelConfig = field(default_factory=ModelConfig)
    project: dict | None = None
    session: ChatSession | None = None
    entry: ModelEntry | None = None
    on_event: Callable = lambda e: None

    def ensure_session(self) -> ChatSession:
        if self.session is None:
            entry = self.entry or self.config.active()
            if entry is None:
                raise ModelConfigError("还没有配置模型：/models add <名称> --preset <提供方> --api-key <密钥>")
            self.entry = entry
            self.session = ChatSession(make_backend(entry), self.project, self.on_event)
        return self.session

    def switch_model(self, entry: ModelEntry) -> None:
        self.entry = entry
        transcript = self.session.transcript if self.session else []
        self.session = ChatSession(make_backend(entry), self.project, self.on_event)
        self.session.transcript = transcript

    def status_line(self) -> str:
        model = f"{self.entry.name}（{self.entry.provider} · {self.entry.model}）" if self.entry else "未配置模型（/models add）"
        proj = f"{self.project['name']} [{self.project['id']}]" if self.project else "未选项目（/project <目录>）"
        return f"模型：{model}    项目：{proj}"


def _add_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="/models add", add_help=False)
    p.add_argument("name")
    p.add_argument("--preset", choices=sorted(PRESETS))
    p.add_argument("--provider", choices=["anthropic", "openai"])
    p.add_argument("--base-url")
    p.add_argument("--model")
    p.add_argument("--api-key")
    p.add_argument("--set-active", action="store_true")
    return p


def handle(line: str, state: ChatState) -> tuple[bool, list[str]]:
    """返回（是不是命令, 要显示的行）。不是命令就交给模型。"""
    text = line.strip()
    if not text.startswith("/"):
        return False, []
    try:
        parts = shlex.split(text, posix=False)  # posix=False：Windows 路径里的反斜杠不能被吃掉
    except ValueError as exc:
        return True, [f"命令解析失败：{exc}"]
    cmd, args = parts[0].lower(), [a.strip("\"'") for a in parts[1:]]
    try:
        if cmd in ("/help", "/h", "/?"):
            return True, HELP.splitlines()
        if cmd == "/quit" or cmd == "/exit":
            return True, ["__QUIT__"]
        if cmd == "/clear":
            if state.session:
                state.session.clear()
            return True, ["对话记录已清空。"]
        if cmd == "/model" and args:
            return True, [_use(state, args[0])]
        if cmd == "/models":
            return True, _models(state, args)
        if cmd == "/project":
            if not args:
                return True, ["用法：/project <目录或 id>"]
            state.project = project_info(args[0])
            if state.session:
                state.session.set_project(state.project)
            return True, [f"已选定项目：{state.project['name']}（{state.project['id']}）", state.project["root"]]
        if cmd == "/next":
            if not state.project:
                return True, ["先 /project <目录> 选一个项目。"]
            env = call("next", {"project": state.project["id"]})
            if not env["ok"]:
                return True, [f"next 失败：{env['error']['message']}"]
            d = env["data"]
            lines = []
            if d["step"]:
                lines.append(f"步骤 {d['step']['id']} {d['step']['title']}（{d['step']['status_label']}）· 现在处于：{d['phase']}")
                if d["missing"]:
                    lines.append("本轮目录还缺：" + "、".join(d["missing"]))
            else:
                lines.append("全部步骤都已结束；用 step_add 登记新步骤。")
            lines += [f"  - {t}" for t in d["todo"]]
            return True, lines
        return True, [f"不认识的命令 {cmd}；/help 看全部。"]
    except (ModelConfigError, ProjectError, LLMError) as exc:
        return True, [f"失败：{exc}"]


def _use(state: ChatState, name: str) -> str:
    entry = state.config.use(name)
    state.switch_model(entry)
    return f"当前模型：{entry.name}（{entry.provider} · {entry.model}）"


def _models(state: ChatState, args: list[str]) -> list[str]:
    if not args or args[0] == "list":
        rows = state.config.list()
        if state.config.last_warning:
            warn, state.config.last_warning = state.config.last_warning, None
            return [f"注意：{warn}"]
        if not rows:
            return ["还没有配置模型。例：/models add 我的deepseek --preset deepseek --api-key sk-…",
                    "预设：" + "、".join(f"{k}（{v['label']}）" for k, v in PRESETS.items())]
        active = state.config.active()
        return [f"{'*' if active and r.name == active.name else ' '} {r.name}  {r.provider} · {r.model}  {r.base_url or ''}  密钥 {r.masked_key()}" for r in rows]
    sub = args[0]
    if sub == "add":
        try:
            ns = _add_parser().parse_args(args[1:])
        except SystemExit:
            return ["用法见 /help：/models add <名称> --preset <提供方> --api-key <密钥> [--model <ID>] [--base-url <地址>] [--set-active]"]
        entry = state.config.add(ns.name, preset=ns.preset, provider=ns.provider, base_url=ns.base_url, model=ns.model,
                                 api_key=ns.api_key, set_active=ns.set_active)
        if state.config.active() and state.config.active().name == entry.name:
            state.switch_model(entry)
        return [f"已保存 {entry.name}：{entry.provider} · {entry.model}  {entry.base_url or ''}  密钥 {entry.masked_key()}",
                f"配置文件：{state.config.path}"]
    if sub == "use" and len(args) > 1:
        return [_use(state, args[1])]
    if sub == "remove" and len(args) > 1:
        state.config.remove(args[1])
        return [f"已删除 {args[1]}"]
    if sub == "status":
        entry = state.entry or state.config.active()
        if entry is None:
            return ["还没有配置模型。"]
        backend = make_backend(entry)
        turn = backend.complete("你是连通性测试。只回复：ok", [{"role": "user", "content": "在吗"}], [])
        return [f"{entry.name} 可用：模型回复「{turn.text.strip()[:40]}」，用量 {turn.usage}"]
    return ["用法见 /help"]
