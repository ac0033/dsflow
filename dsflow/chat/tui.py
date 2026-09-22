"""`dsflow chat` 的全屏终端界面（Textual）：顶部横幅与状态、中间对话与工具调用记录、底部输入框。"""

from __future__ import annotations

import json

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Input, RichLog, Static

from .. import __version__
from .commands import HELP, ChatState, handle

BANNER = r"""
  ____  ____  _____ _
 |  _ \/ ___||  ___| | _____      __
 | | | \___ \| |_  | |/ _ \ \ /\ / /
 | |_| |___) |  _| | | (_) \ V  V /
 |____/|____/|_|   |_|\___/ \_/\_/
"""


class ChatApp(App):
    CSS = """
    Screen { layout: vertical; }
    #banner { height: auto; color: $accent; padding: 0 1; }
    #status { height: 1; background: $surface; color: $text-muted; padding: 0 1; }
    #log { height: 1fr; border: round $primary; padding: 0 1; }
    #input { dock: bottom; }
    """
    BINDINGS = [Binding("ctrl+c", "quit", "退出"), Binding("ctrl+l", "clear_log", "清屏")]
    TITLE = "DSFlow"

    def __init__(self, state: ChatState):
        super().__init__()
        self.state = state
        self.state.on_event = self._on_event
        if self.state.session:
            self.state.session.on_event = self._on_event
        self.busy = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(BANNER + f"  DSFlow 终端客户端 v{__version__}", id="banner")
            yield Static(self.state.status_line(), id="status")
            yield RichLog(id="log", wrap=True, markup=True, highlight=False)
            yield Input(placeholder="输入要求，或 /help 看命令", id="input")
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("[bold]欢迎使用 DSFlow 终端客户端。[/bold]")
        if not self.state.entry and not self.state.config.active():
            log.write("1. 先配模型：/models add 我的模型 --preset deepseek --api-key sk-…（预设见 /help）")
        if not self.state.project:
            log.write("2. 再选项目：/project <项目目录>")
        log.write("3. 然后直接输入你的要求，例如「看看现在到哪一步了，给下一步的计划」。")
        self.query_one("#input", Input).focus()

    def _log(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)

    def _refresh_status(self) -> None:
        self.query_one("#status", Static).update(self.state.status_line())

    def _on_event(self, event) -> None:
        kind, payload = event
        if kind == "tool":
            args = json.dumps(payload["args"], ensure_ascii=False)
            self.call_from_thread(self._log, f"[dim]→ 调用 {payload['name']} {args[:200]}[/dim]")
        elif kind == "result":
            env = payload["envelope"]
            mark = "[green]✓[/green]" if payload["ok"] else "[red]✗[/red]"
            detail = "" if payload["ok"] else f" {env['error']['message']}（{env['error'].get('hint', '')}）"
            self.call_from_thread(self._log, f"[dim]{mark} {payload['name']}{detail}[/dim]")
        elif kind == "text":
            self.call_from_thread(self._log, f"[cyan]agent[/cyan]  {payload['text']}")
        elif kind == "error":
            self.call_from_thread(self._log, f"[red]出错：{payload['message']}[/red]")
        elif kind == "info":
            self.call_from_thread(self._log, f"[yellow]{payload['message']}[/yellow]")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        self._log(f"[bold]你[/bold]  {text}")
        handled, lines = handle(text, self.state)
        if handled:
            for line in lines:
                if line == "__QUIT__":
                    self.exit()
                    return
                self._log(line)
            self._refresh_status()
            return
        if self.busy:
            self._log("[yellow]上一轮还在进行，等它回复后再发。[/yellow]")
            return
        self._send(text)

    @work(thread=True, exclusive=True)
    def _send(self, text: str) -> None:
        self.busy = True
        try:
            session = self.state.ensure_session()
            self.call_from_thread(self._refresh_status)
            session.send(text)
        except Exception as exc:  # noqa: BLE001 — 界面里任何错误都要显示出来
            self.call_from_thread(self._log, f"[red]{exc}[/red]")
        finally:
            self.busy = False

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()
        self._log(HELP.splitlines()[0])
