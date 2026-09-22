"""两类模型后端，同一个接口：`complete(system, transcript, tools) -> Turn`。

内部对话记录（transcript）与提供方无关：
  {"role": "user", "content": "…"}
  {"role": "assistant", "content": "…", "tool_calls": [{"id", "name", "args"}]}
  {"role": "tool", "id": "…", "name": "…", "content": "…（JSON 文本）"}
两个后端各自把它转成自家的消息格式；工具定义来自协议登记表（dsflow/protocol.py）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from .config import ModelEntry

MAX_TOKENS = 16000


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Turn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop: str = "end"  # end / tool / max_tokens / refusal
    usage: dict = field(default_factory=dict)


class LLMError(Exception):
    pass


def tool_specs() -> list[dict]:
    """协议工具 → 通用定义 {name, description, parameters}。"""
    from ..protocol import REGISTRY

    return [{"name": s.name, "description": s.description, "parameters": s.schema()} for s in REGISTRY.values()]


class Backend:
    def __init__(self, entry: ModelEntry | None = None):
        self.entry = entry

    def complete(self, system: str, transcript: list[dict], tools: list[dict]) -> Turn:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def stream(self, system: str, transcript: list[dict], tools: list[dict], on_text: Callable[[str], None]) -> Turn:
        """边出边给：每来一段文字就调一次 on_text，最后返回整轮结果。

        默认实现是一次性拿完再整段交出去；网页上的答疑对话框用它显示打字效果，后端不支持流式也能正常工作。
        """
        turn = self.complete(system, transcript, tools)
        if turn.text:
            on_text(turn.text)
        return turn


# ---------- Anthropic（官方 SDK） ----------


def to_anthropic_messages(transcript: list[dict]) -> list[dict]:
    out: list[dict] = []
    pending_results: list[dict] = []
    for m in transcript:
        if m["role"] == "tool":
            pending_results.append({"type": "tool_result", "tool_use_id": m["id"], "content": m["content"]})
            continue
        if pending_results:
            out.append({"role": "user", "content": pending_results})
            pending_results = []
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        else:
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for c in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]})
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
    if pending_results:
        out.append({"role": "user", "content": pending_results})
    return out


def to_anthropic_tools(tools: list[dict]) -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]


class AnthropicBackend(Backend):
    def __init__(self, entry: ModelEntry):
        super().__init__(entry)
        import anthropic

        key = entry.resolve_key()
        kwargs = {"api_key": key} if key else {}
        if entry.base_url:
            kwargs["base_url"] = entry.base_url
        self.client = anthropic.Anthropic(**kwargs)
        self.errors = anthropic

    @contextmanager
    def _guard(self) -> Iterator[None]:
        """把 SDK 的异常翻成一句用户看得懂的话；请求和流式读取都用它。"""
        try:
            yield
        except self.errors.AuthenticationError as exc:
            raise LLMError(f"密钥无效：{exc.message}") from exc
        except self.errors.NotFoundError as exc:
            raise LLMError(f"模型或地址不存在：{exc.message}") from exc
        except self.errors.RateLimitError as exc:
            raise LLMError(f"触发限流，稍后再试：{exc.message}") from exc
        except self.errors.APIStatusError as exc:
            raise LLMError(f"接口返回 {exc.status_code}：{exc.message}") from exc
        except self.errors.APIConnectionError as exc:
            raise LLMError(f"连不上接口：{exc}") from exc

    def stream(self, system: str, transcript: list[dict], tools: list[dict], on_text: Callable[[str], None]) -> Turn:
        with self._guard():
            with self.client.messages.stream(
                model=self.entry.model, max_tokens=MAX_TOKENS, system=system,
                messages=to_anthropic_messages(transcript), tools=to_anthropic_tools(tools),
            ) as stream:
                for piece in stream.text_stream:
                    on_text(piece)
                return self._turn(stream.get_final_message())

    def complete(self, system: str, transcript: list[dict], tools: list[dict]) -> Turn:
        with self._guard():
            response = self.client.messages.create(
                model=self.entry.model, max_tokens=MAX_TOKENS, system=system,
                messages=to_anthropic_messages(transcript), tools=to_anthropic_tools(tools),
            )
        return self._turn(response)

    def _turn(self, response) -> Turn:
        turn = Turn(usage={"input": response.usage.input_tokens, "output": response.usage.output_tokens})
        if response.stop_reason == "refusal":
            turn.stop = "refusal"
        elif response.stop_reason == "max_tokens":
            turn.stop = "max_tokens"
        texts = []
        for block in response.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                turn.tool_calls.append(ToolCall(block.id, block.name, dict(block.input or {})))
        turn.text = "\n".join(t for t in texts if t)
        if turn.tool_calls:
            turn.stop = "tool"
        return turn


# ---------- OpenAI 兼容（官方 openai SDK，base_url 指向任一兼容服务） ----------


def to_openai_messages(system: str, transcript: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in transcript:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            msg: dict = {"role": "assistant", "content": m.get("content") or None}
            if m.get("tool_calls"):
                msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                      "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
                                     for c in m["tool_calls"]]
            out.append(msg)
        else:
            out.append({"role": "tool", "tool_call_id": m["id"], "content": m["content"]})
    return out


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in tools]


class OpenAIBackend(Backend):
    def __init__(self, entry: ModelEntry):
        super().__init__(entry)
        import openai

        key = entry.resolve_key()
        self.client = openai.OpenAI(api_key=key or "no-key", base_url=entry.base_url or None)
        self.errors = openai

    @contextmanager
    def _guard(self) -> Iterator[None]:
        """把 SDK 的异常翻成一句用户看得懂的话；请求和流式读取都用它。"""
        try:
            yield
        except self.errors.AuthenticationError as exc:
            raise LLMError(f"密钥无效：{exc}") from exc
        except self.errors.NotFoundError as exc:
            raise LLMError(f"模型或地址不存在：{exc}") from exc
        except self.errors.RateLimitError as exc:
            raise LLMError(f"触发限流，稍后再试：{exc}") from exc
        except self.errors.APIStatusError as exc:
            raise LLMError(f"接口返回 {exc.status_code}：{exc}") from exc
        except self.errors.APIConnectionError as exc:
            raise LLMError(f"连不上接口：{exc}") from exc

    def stream(self, system: str, transcript: list[dict], tools: list[dict], on_text: Callable[[str], None]) -> Turn:
        """OpenAI 兼容接口的流式：文字逐段回调，工具调用按 index 拼起来（名字和参数是分片来的）。"""
        turn = Turn()
        texts: list[str] = []
        calls: dict[int, dict] = {}
        finish = ""
        with self._guard():
            stream = self.client.chat.completions.create(
                model=self.entry.model, messages=to_openai_messages(system, transcript),
                tools=to_openai_tools(tools) or None, max_tokens=MAX_TOKENS, stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                finish = choice.finish_reason or finish
                delta = choice.delta
                if getattr(delta, "content", None):
                    texts.append(delta.content)
                    on_text(delta.content)
                for tc in getattr(delta, "tool_calls", None) or []:
                    slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments
        turn.text = "".join(texts)
        for slot in (calls[i] for i in sorted(calls)):
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": slot["args"]}
            turn.tool_calls.append(ToolCall(slot["id"] or f"call_{len(turn.tool_calls)}", slot["name"], args))
        if turn.tool_calls:
            turn.stop = "tool"
        elif finish == "length":
            turn.stop = "max_tokens"
        return turn

    def complete(self, system: str, transcript: list[dict], tools: list[dict]) -> Turn:
        with self._guard():
            response = self.client.chat.completions.create(
                model=self.entry.model, messages=to_openai_messages(system, transcript),
                tools=to_openai_tools(tools) or None, max_tokens=MAX_TOKENS,
            )
        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        turn = Turn(text=choice.message.content or "", usage={"input": getattr(usage, "prompt_tokens", 0), "output": getattr(usage, "completion_tokens", 0)})
        for c in choice.message.tool_calls or []:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": c.function.arguments}
            turn.tool_calls.append(ToolCall(c.id, c.function.name, args))
        if turn.tool_calls:
            turn.stop = "tool"
        elif choice.finish_reason == "length":
            turn.stop = "max_tokens"
        return turn


def make_backend(entry: ModelEntry) -> Backend:
    if entry.provider == "anthropic":
        return AnthropicBackend(entry)
    if entry.provider == "openai":
        return OpenAIBackend(entry)
    raise LLMError(f"不认识的 provider：{entry.provider}")
