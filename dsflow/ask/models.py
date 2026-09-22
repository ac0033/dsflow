"""在网页上配答疑用的模型：选一家、填密钥、保存、测一下通不通。

和 `dsflow chat` 的 `/models` 命令写的是同一份 `<DSFLOW_HOME>/models.json`，两边配好的互相都能用。
密钥只进本机这个文件，接口从不把它原样返回（只返回打码后的样子）。
"""

from __future__ import annotations

from ..chat.config import GENERIC_ENV, PRESETS, ModelConfig, ModelConfigError, ModelEntry
from ..chat.llm import LLMError, make_backend

TEST_QUESTION = "回答两个字：可以。"


def presets() -> list[dict]:
    """给网页的下拉框用：哪几家、默认模型、去哪里申请密钥、要不要密钥。"""
    return [{"preset": key, "label": value["label"], "model": value["model"], "base_url": value["base_url"],
             "where": value.get("where", ""), "needs_key": key != "ollama", "env": value.get("env", "")}
            for key, value in PRESETS.items()]


def _row(entry: ModelEntry, active: str | None) -> dict:
    return {"name": entry.name, "provider": entry.provider, "model": entry.model, "base_url": entry.base_url,
            "preset": entry.preset, "key": entry.masked_key(), "ready": entry.resolve_key() is not None,
            "active": entry.name == active}


def listing() -> dict:
    """配过的模型 + 可选的厂商；密钥只给打码后的样子。"""
    config = ModelConfig()
    active = config.active()
    return {"models": [_row(m, active.name if active else None) for m in config.list()],
            "presets": presets(), "path": str(config.path), "env_hint": GENERIC_ENV}


def save(preset: str, api_key: str = "", name: str = "", model: str = "", base_url: str = "") -> dict:
    """存一个模型并设为当前使用的那个。名字不填就用这家的中文名。"""
    if preset not in PRESETS and not (model and base_url):
        raise ModelConfigError("选一家模型服务；自己填地址时要写清模型 ID 与接口地址。")
    base = PRESETS.get(preset, {})
    label = name.strip() or base.get("label") or preset
    if preset != "ollama" and not api_key.strip() and not ModelEntry(name=label, provider=base.get("provider", "openai"),
                                                                    model="x", preset=preset).resolve_key():
        raise ModelConfigError(f"这家要密钥。把密钥粘进来，或者先设好环境变量 {base.get('env') or GENERIC_ENV} 再刷新页面。")
    config = ModelConfig()
    entry = config.add(label, preset=preset if preset in PRESETS else None,
                       provider=base.get("provider") or "openai",
                       base_url=base_url.strip() or base.get("base_url"),
                       model=model.strip() or base.get("model"),
                       api_key=api_key.strip() or None, set_active=True)
    return _row(entry, entry.name)


def use(name: str) -> dict:
    config = ModelConfig()
    entry = config.use(name)
    return _row(entry, entry.name)


def remove(name: str) -> dict:
    config = ModelConfig()
    config.remove(name)
    active = config.active()
    return {"removed": name, "active": active.name if active else None}


def test(name: str = "") -> dict:
    """真的发一句最短的话过去，看通不通。通了返回模型回的那句，不通返回一句人能看懂的原因。"""
    config = ModelConfig()
    entry = config.get(name) if name else config.active()
    if entry is None:
        return {"ok": False, "message": "还没有配模型。"}
    if entry.resolve_key() is None:
        return {"ok": False, "message": f"没有可用的密钥：{entry.masked_key()}。"}
    try:
        turn = make_backend(entry).complete("你是连通性测试，只回四个字以内。",
                                            [{"role": "user", "content": TEST_QUESTION}], [])
    except LLMError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - 装没装 SDK、地址写错都要给一句话
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "message": (turn.text or "").strip()[:40] or "接口通了，但这一句没有回文字。", "model": entry.model}
