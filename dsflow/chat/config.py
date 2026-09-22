"""模型配置：像瑞幸 CLI 那样 `/models add <名称> --provider … --base-url … --model … --api-key …`，存在本机平台目录的 models.json。

两类协议覆盖绝大多数提供方：
- anthropic：Claude（官方 SDK）。
- openai：OpenAI 兼容接口（OpenAI、DeepSeek、通义千问、Kimi、智谱、OpenRouter、Ollama……只是 base_url 不同）。

密钥怎么放，用户方便就行：直接写在配置里（文件权限 600），或写成 `env:变量名` 从环境变量取；
配置里没有密钥时按提供方读常用环境变量（ANTHROPIC_API_KEY / OPENAI_API_KEY / DSFLOW_LLM_API_KEY）。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..paths import dsflow_home

# where：去哪里申请密钥，网页上的配置表单直接显示给不熟悉的人看。
PRESETS: dict[str, dict] = {
    "anthropic": {"provider": "anthropic", "base_url": None, "model": "claude-opus-5", "env": "ANTHROPIC_API_KEY",
                  "label": "Claude（Anthropic 官方）", "where": "console.anthropic.com 的 API Keys 页面"},
    "openai": {"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-5", "env": "OPENAI_API_KEY",
               "label": "OpenAI", "where": "platform.openai.com 的 API keys 页面"},
    "deepseek": {"provider": "openai", "base_url": "https://api.deepseek.com", "model": "deepseek-chat", "env": "DEEPSEEK_API_KEY",
                 "label": "DeepSeek", "where": "platform.deepseek.com 的 API keys 页面"},
    "qwen": {"provider": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "env": "DASHSCOPE_API_KEY",
             "label": "通义千问（DashScope）", "where": "阿里云百炼控制台的 API-KEY 页面"},
    "moonshot": {"provider": "openai", "base_url": "https://api.moonshot.cn/v1", "model": "kimi-k2-0905-preview", "env": "MOONSHOT_API_KEY",
                 "label": "Kimi（Moonshot）", "where": "platform.moonshot.cn 的 API Key 管理页面"},
    "zhipu": {"provider": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4.6", "env": "ZHIPU_API_KEY",
              "label": "智谱", "where": "bigmodel.cn 的 API Keys 页面"},
    "openrouter": {"provider": "openai", "base_url": "https://openrouter.ai/api/v1", "model": "anthropic/claude-sonnet-4.6", "env": "OPENROUTER_API_KEY",
                   "label": "OpenRouter", "where": "openrouter.ai 的 Keys 页面"},
    "ollama": {"provider": "openai", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen3", "env": "",
               "label": "Ollama（本机，不需要密钥）", "where": "本机跑的模型，不需要密钥"},
}
GENERIC_ENV = "DSFLOW_LLM_API_KEY"


@dataclass
class ModelEntry:
    name: str
    provider: str  # anthropic / openai
    model: str
    base_url: str | None = None
    api_key: str | None = None  # 明文，或 "env:变量名"
    preset: str | None = None
    extra: dict = field(default_factory=dict)

    def resolve_key(self) -> str | None:
        """明文 → env:变量 → 预设的常用环境变量 → DSFLOW_LLM_API_KEY。Ollama 这类不需要密钥的返回空串。"""
        raw = self.api_key or ""
        if raw.startswith("env:"):
            return os.environ.get(raw[4:]) or None
        if raw:
            return raw
        env = PRESETS.get(self.preset or "", {}).get("env")
        if env and os.environ.get(env):
            return os.environ[env]
        if os.environ.get(GENERIC_ENV):
            return os.environ[GENERIC_ENV]
        return "" if self.preset == "ollama" else None

    def masked_key(self) -> str:
        raw = self.api_key or ""
        if raw.startswith("env:"):
            return raw
        if not raw:
            env = PRESETS.get(self.preset or "", {}).get("env")
            return f"（未配置，将读环境变量 {env or GENERIC_ENV}）"
        return raw[:6] + "…" + raw[-4:] if len(raw) > 12 else "…"

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "name"}


class ModelConfigError(Exception):
    pass


class ModelConfig:
    """models.json 的读写：增删、切换当前模型、列表。"""

    def __init__(self, path: Path | None = None):
        self.path = path or dsflow_home() / "models.json"
        self.last_warning: str | None = None

    def _load(self) -> dict:
        if not self.path.is_file():
            return {"active": None, "models": {}}
        text = self.path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return {"active": None, "models": {}}  # 空文件当没有
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 坏文件不能让客户端再也起不来：挪到 .bad 备份，从空配置开始
            bad = self.path.with_suffix(".json.bad")
            self.path.replace(bad)
            self.last_warning = f"{self.path} 不是合法 JSON，已挪到 {bad.name}，请重新 /models add"
            return {"active": None, "models": {}}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("active", None)
        data.setdefault("models", {})
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        text = text.encode("utf-8", errors="replace").decode("utf-8")  # 管道进来的代理字符不能写进文件
        tmp = self.path.with_suffix(f".json.tmp{os.getpid()}")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.path)  # 先写临时文件再替换：写一半崩溃也不会留下空文件
        try:
            os.chmod(self.path, 0o600)  # 里面有密钥；Windows 上此调用只影响只读位，无害
        except OSError:
            pass

    def list(self) -> list[ModelEntry]:
        data = self._load()
        return [ModelEntry(name=n, **v) for n, v in data["models"].items()]

    def get(self, name: str) -> ModelEntry:
        data = self._load()
        if name not in data["models"]:
            raise ModelConfigError(f"没有叫 {name} 的模型；先 /models add")
        return ModelEntry(name=name, **data["models"][name])

    def active(self) -> ModelEntry | None:
        data = self._load()
        name = data.get("active")
        if name and name in data["models"]:
            return ModelEntry(name=name, **data["models"][name])
        return None

    def add(self, name: str, *, preset: str | None = None, provider: str | None = None, base_url: str | None = None,
            model: str | None = None, api_key: str | None = None, set_active: bool = False) -> ModelEntry:
        """预设只是填默认值：`/models add 我的deepseek --preset deepseek --api-key sk-…`；也可以全手填。"""
        base = PRESETS.get(preset or name) or {}
        prov = provider or base.get("provider")
        if prov not in ("anthropic", "openai"):
            raise ModelConfigError("provider 只能是 anthropic 或 openai（OpenAI 兼容接口）；或用 --preset " + " / ".join(PRESETS))
        name = name.encode("utf-8", errors="replace").decode("utf-8")
        entry = ModelEntry(name=name, provider=prov, model=model or base.get("model") or "",
                           base_url=base_url if base_url is not None else base.get("base_url"),
                           api_key=api_key, preset=preset or (name if name in PRESETS else None))
        if not entry.model:
            raise ModelConfigError("要指定 --model <模型 ID>")
        data = self._load()
        data["models"][name] = entry.to_dict()
        if set_active or not data.get("active"):
            data["active"] = name
        self._save(data)
        return entry

    def remove(self, name: str) -> None:
        data = self._load()
        if name not in data["models"]:
            raise ModelConfigError(f"没有叫 {name} 的模型")
        del data["models"][name]
        if data.get("active") == name:
            data["active"] = next(iter(data["models"]), None)
        self._save(data)

    def use(self, name: str) -> ModelEntry:
        entry = self.get(name)
        data = self._load()
        data["active"] = name
        self._save(data)
        return entry
