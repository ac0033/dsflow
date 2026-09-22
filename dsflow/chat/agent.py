"""对话会话：用户说一句 → 模型（带协议工具）→ 工具循环 → 回复。TUI 和纯文本模式都用它。

模型看到的系统提示 = 接口 skill（skills/dsflow-project/SKILL.md）+ 当前项目 + 工作规矩（dsflow/core/rules.py）+ 几条终端场景的规矩。
工具执行走 dsflow/protocol.py 的 call()，和命令行、MCP、HTTP 完全一致；`project` 参数缺了就自动补当前项目。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from ..core.rules import one_line
from ..paths import skills_dir
from ..protocol import call
from .llm import Backend, LLMError, Turn, tool_specs

MAX_TOOL_ROUNDS = 30
Event = tuple[str, dict]  # ("text"|"tool"|"result"|"error"|"info", payload)


def system_prompt(project: dict | None) -> str:
    skill = skills_dir() / "dsflow-project" / "SKILL.md"
    body = skill.read_text(encoding="utf-8") if skill.is_file() else ""
    if body.startswith("---"):
        body = body.split("---", 2)[-1]
    where = (f"当前项目：id `{project['id']}`，目录 `{project['root']}`，名称「{project['name']}」。调用工具时 project 参数写这个 id。"
             if project else "现在还没有选定项目：先让用户用 /project <目录> 选一个，或用 projects_list 看有哪些。")
    return (
        "你是 DSFlow 终端客户端里的 agent，在终端里和用户对话，通过工具在平台上推进数据科学项目。\n"
        f"{where}\n"
        "你同时担任主 agent（写计划、验收）和执行 agent（执行、写报告与讲解）两个角色，除非用户另行安排了独立的执行 agent。\n"
        f"工作规矩：{one_line()}\n"
        "终端里的规矩：动手之前先调 next；按 tool_calls 做；每次只做当前环节的事；交完计划或验收报告后停下来向用户汇报，"
        "等用户在网页或这里表态（用户在这里说通过 / 退回，就调 approval_decide 记录原话）；不替用户改状态；"
        "工具返回 ok=false 就按 hint 改，不要绕开。回复用中文，每句话带具体宾语，以句号结尾。\n\n"
        "以下是接入 DSFlow 的接口 skill 原文：\n" + body.strip()
    )


class ChatSession:
    def __init__(self, backend: Backend, project: dict | None = None, on_event: Callable[[Event], None] | None = None):
        self.backend = backend
        self.project = project
        self.on_event = on_event or (lambda e: None)
        self.transcript: list[dict] = []
        self.tools = tool_specs()

    def set_project(self, project: dict | None) -> None:
        self.project = project

    def _run_tool(self, name: str, args: dict) -> str:
        args = dict(args or {})
        if self.project and "project" in self._params(name) and not args.get("project"):
            args["project"] = self.project["id"]
        self.on_event(("tool", {"name": name, "args": args}))
        env = call(name, args)
        text = json.dumps(env, ensure_ascii=False, default=str)
        if len(text) > 60_000:
            text = text[:60_000] + "…（已截断）"
        self.on_event(("result", {"name": name, "ok": env.get("ok", False), "envelope": env}))
        return text

    def _params(self, name: str) -> set[str]:
        for t in self.tools:
            if t["name"] == name:
                return set(t["parameters"]["properties"])
        return set()

    def send(self, text: str) -> str:
        """一轮对话：返回模型最后的回复文本；过程中的工具调用通过 on_event 通知界面。"""
        self.transcript.append({"role": "user", "content": text})
        system = system_prompt(self.project)
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                turn: Turn = self.backend.complete(system, self.transcript, self.tools)
            except LLMError as exc:
                self.on_event(("error", {"message": str(exc)}))
                self.transcript.pop() if self.transcript and self.transcript[-1]["role"] == "user" else None
                return ""
            self.transcript.append({"role": "assistant", "content": turn.text,
                                    "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in turn.tool_calls]})
            if turn.text:
                self.on_event(("text", {"text": turn.text}))
            if turn.stop == "refusal":
                self.on_event(("info", {"message": "模型拒绝了这个请求。"}))
                return turn.text
            if not turn.tool_calls:
                return turn.text
            for c in turn.tool_calls:
                result = self._run_tool(c.name, c.args)
                self.transcript.append({"role": "tool", "id": c.id, "name": c.name, "content": result})
        self.on_event(("info", {"message": f"连续调用工具超过 {MAX_TOOL_ROUNDS} 次，先停下来。"}))
        return ""

    def clear(self) -> None:
        self.transcript.clear()


def project_info(ref: str) -> dict:
    """目录或 id → {id, root, name}；未登记的目录顺手登记为可写。"""
    from ..core.project import ProjectError, project_id_for
    from ..index.db import PlatformIndex

    index = PlatformIndex()
    row = index.get_project(ref) if len(ref) == 10 and not Path(ref).exists() else None
    if row is None:
        root = Path(ref).resolve()
        if not (root / "dsflow.yaml").is_file():
            raise ProjectError(f"{root} 不是 DSFlow 项目（没有 dsflow.yaml）；先 dsflow init 或 dsflow attach")
        row = index.get_project(project_id_for(root)) or index.add_project(root, readonly=False)
    return {"id": row["id"], "root": row["root"], "name": row["name"]}
