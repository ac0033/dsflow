"""一轮问答：组装上下文 → 模型（可调只读工具）→ 逐段吐字 → 核对数字 → 存档。

回答受和讲解一样的约束：用登记过的术语、不换说法、每句话带具体宾语、数字要有出处。
答完以后平台自己再核一遍数字：答案里出现、却在上下文和工具返回里找不到的数字会标出来，界面上灰掉提醒用户。
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Iterator

from ..chat.config import ModelConfig, ModelEntry
from ..chat.llm import Backend, LLMError, ToolCall, Turn, make_backend
from ..core.project import Project
from ..core.schemas import Registry
from ..explain.guide import found_in, numbers_in
from . import tools as ask_tools
from .context import Scope, build, guess_file
from .links import find_links
from .store import AskStore, Record

MAX_ROUNDS = 6          # 一轮提问里最多让模型调几次工具
MAX_HISTORY = 6         # 同一条线上带几轮旧问答
MAX_TOOL_TEXT = 20_000  # 单次工具返回喂给模型的上限


class AskError(Exception):
    pass


def system_prompt(with_tools: bool) -> str:
    return (
        "你是 DSFlow 平台里的答疑助手。读者是懂业务、懂技术原理、能读代码，但没做过数据科学的项目负责人，"
        "他正在平台上看一个已经做过的数据科学项目，随手选中一句话来问你。\n"
        "怎么答：\n"
        "1. 先给结论，再解释为什么；一个问题一般 200 字以内答完，用户要求展开再展开。\n"
        "2. 行话、缩写、指标名先用白话说它解决什么问题，再给定义，然后回到用户选中的那句话上说它在这里是什么意思。\n"
        "3. 数据表、列、文件、步骤都用上下文里的原名，别换说法、别造新词；上下文里给了术语表就照术语表的说法。\n"
        "4. 每句话的动词都要带具体宾语，以句号结尾，不用口语缩略说法。\n"
        "5. 数字只能照抄上下文或工具返回里的原样，不估算、不推算；上下文里没有就说没有，并说明去哪一步能看到。\n"
        "6. 不知道就说不知道，不要用常识补一个像样的答案。\n"
        + ("7. 需要更多材料时就去读，别凭这一屏猜：`file_read` 读代码、notebook、计划与报告的原文；`data_peek` 看一张表的"
           "前几行与全部列名；`data_query` 对这张表跑一条只读 SQL（表名写 data）数一数、分组汇总；`step_get` 看某一步"
           "本轮有哪些文件，`guide_get` 看讲解，`runs_list` / `run_get` 看运行记录。data_query 说这张表还没转换时改用 "
           "data_peek，并告诉用户在数据页打开一次这张表就能查。工具只能读，不能改项目；"
           "用户要求改东西时，告诉他去让这个项目的主 agent 安排，并说清该调哪个工具。\n" if with_tools else
           "7. 你这一轮没有工具可用，只能用上下文里的材料回答；材料不够就直说缺什么。\n")
        + "用中文回答，可以用 Markdown 的小标题、列表和加粗。"
    )


def active_model() -> ModelEntry:
    entry = ModelConfig().active()
    if entry is None:
        raise AskError("还没有配置模型：在对话框顶部点模型那一栏，选一家、把密钥粘进来，点「保存并连接」即可。终端里的 dsflow chat 也能配，两边是同一份配置。")
    if entry.resolve_key() is None:
        raise AskError(f"模型「{entry.name}」还没有可用的密钥：在对话框顶部点模型那一栏重新填一次密钥，或设好对应的环境变量再刷新页面。")
    return entry


def status() -> dict:
    """界面用来判断答疑能不能用：有没有模型、是哪一个、缺什么。"""
    config = ModelConfig()
    entry = config.active()
    names = [m.name for m in config.list()]
    if entry is None:
        return {"ready": False, "model": None, "models": names,
                "hint": "还没有配置模型。在下面选一家、把密钥粘进来，点「保存并连接」就能用。"}
    if entry.resolve_key() is None:
        return {"ready": False, "model": entry.name, "provider": entry.provider, "models": names,
                "hint": f"模型「{entry.name}」没有可用的密钥（{entry.masked_key()}）。在下面重新填一次。"}
    return {"ready": True, "model": entry.name, "provider": entry.provider, "model_id": entry.model, "models": names, "hint": ""}


def _tool_text(envelope: dict) -> str:
    text = json.dumps(envelope, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_TOOL_TEXT else text[:MAX_TOOL_TEXT] + "…（已截断，需要就换更小的范围再读一次）"


def _run_tool(project_id: str, call: ToolCall) -> tuple[dict, str]:
    from ..protocol import call as protocol_call, envelope_error

    if not ask_tools.allowed(call.name):
        env = envelope_error("forbidden", f"答疑只能用只读工具，{call.name} 不在名单里",
                             "能用的工具：" + "、".join(ask_tools.READONLY))
        return env, _tool_text(env)
    args = dict(call.args or {})
    args.setdefault("project", project_id)
    env = protocol_call(call.name, args)
    return env, _tool_text(env)


def _unverified(answer: str, sources: str, skip: set[str]) -> list[str]:
    """答案里没能在上下文或工具返回里找到出处的数字。"""
    out: list[str] = []
    for raw in numbers_in(answer, skip):
        if not found_in(raw, sources) and raw not in out:
            out.append(raw)
    return out[:10]


def _transcript(context_text: str, question: str, history: list[dict]) -> list[dict]:
    lines = [context_text, "", "用户的问题：" + question]
    out: list[dict] = []
    for turn in history[-MAX_HISTORY:]:
        if turn.get("question"):
            out.append({"role": "user", "content": turn["question"]})
            out.append({"role": "assistant", "content": turn.get("answer") or ""})
    out.append({"role": "user", "content": "\n".join(lines)})
    return out


def answer(project: Project, reg: Registry | None, scope: Scope, question: str, *,
           history: list[dict] | None = None, use_tools: bool = True,
           backend: Backend | None = None, model_name: str = "") -> Iterator[dict]:
    """跑一轮问答，按事件往外吐：tool / result / text / done / error。

    事件在工作线程里产生、主线程里吐出去，网页那边按 SSE 一条条收。
    """
    question = (question or "").strip()
    if not question:
        raise AskError("请先写下你的问题。")
    if backend is None:
        entry = active_model()
        backend = make_backend(entry)
        model_name = entry.name
    scope.file = guess_file(project, reg, scope) or scope.file
    context = build(project, reg, scope)
    specs = ask_tools.specs() if use_tools else []
    store = AskStore(project)
    record = Record(id=store.new_id(), at=time.time(), question=question, step=scope.step or "",
                    rev=scope.rev or "", tab=scope.tab or "", file=scope.file or "", quote=scope.quote,
                    notes=[dict(n) for n in scope.notes], mark=scope.pinned, model=model_name)
    skip = {s.id for s in reg.steps} if reg is not None else set()

    events: queue.Queue = queue.Queue()

    def work() -> None:
        pieces: list[str] = []
        sources = [context.sources]

        def on_text(piece: str) -> None:
            pieces.append(piece)
            events.put({"type": "text", "delta": piece})

        try:
            transcript = _transcript(context.text, question, history or [])
            for _ in range(MAX_ROUNDS):
                turn: Turn = backend.stream(system_prompt(bool(specs)), transcript, specs, on_text)
                transcript.append({"role": "assistant", "content": turn.text,
                                   "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in turn.tool_calls]})
                if not turn.tool_calls:
                    break
                for call in turn.tool_calls:
                    events.put({"type": "tool", "name": call.name, "args": call.args})
                    env, text = _run_tool(project.id, call)
                    record.tools.append(call.name)
                    sources.append(text)
                    events.put({"type": "result", "name": call.name, "ok": bool(env.get("ok")),
                                "message": "" if env.get("ok") else (env.get("error") or {}).get("message", "")})
                    transcript.append({"role": "tool", "id": call.id, "name": call.name, "content": text})
            record.answer = "".join(pieces).strip()
            record.unverified = _unverified(record.answer, "\n".join(sources), skip)
            record.links = find_links(project, reg, record.answer, scope.step)
            if not record.answer:
                record.error = "模型这一轮没有给出文字回答，再问一次试试。"
        except LLMError as exc:
            record.error = str(exc)
        except Exception as exc:  # noqa: BLE001 - 后台线程里的异常也要送回界面
            record.error = f"{type(exc).__name__}: {exc}"
        try:
            store.add(record)
        except OSError as exc:
            record.error = record.error or f"问答没能存下来：{exc}"
        events.put({"type": "error", "message": record.error} if record.error and not record.answer else
                   {"type": "done", "record": record.to_dict()})
        events.put(None)

    thread = threading.Thread(target=work, name="dsflow-ask", daemon=True)
    thread.start()
    while True:
        event = events.get()
        if event is None:
            break
        yield event
