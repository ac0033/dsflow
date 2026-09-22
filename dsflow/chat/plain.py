"""`dsflow chat --plain`：不画界面的纯文本模式，给不支持全屏终端的环境（CI、管道、部分 IDE 终端）。"""

from __future__ import annotations

import json
import sys

from .commands import ChatState, handle


def print_event(event) -> None:
    kind, payload = event
    if kind == "tool":
        print(f"  → 调用 {payload['name']} {json.dumps(payload['args'], ensure_ascii=False)[:200]}")
    elif kind == "result":
        env = payload["envelope"]
        print(f"  {'✓' if payload['ok'] else '✗'} {payload['name']}" + ("" if payload["ok"] else f" {env['error']['message']}"))
    elif kind == "text":
        print(f"agent  {payload['text']}")
    elif kind == "error":
        print(f"出错：{payload['message']}")
    elif kind == "info":
        print(payload["message"])
    sys.stdout.flush()


def run_plain(state: ChatState, lines=None) -> None:
    state.on_event = print_event
    if state.session:
        state.session.on_event = print_event
    print(state.status_line())
    print("输入要求；/help 看命令；/quit 退出。")
    source = iter(lines) if lines is not None else None
    while True:
        try:
            text = next(source) if source is not None else input("你  ")
        except (EOFError, StopIteration, KeyboardInterrupt):
            print()
            return
        text = text.strip()
        if not text:
            continue
        handled, out = handle(text, state)
        if handled:
            for line in out:
                if line == "__QUIT__":
                    return
                print(line)
            continue
        try:
            state.ensure_session().send(text)
        except Exception as exc:  # noqa: BLE001
            print(f"失败：{exc}")
