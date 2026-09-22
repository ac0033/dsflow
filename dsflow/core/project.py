"""一个被管项目的只读视图：定位配置与注册表、校验、安全读取项目内文件。

只读项目（默认）的任何平台状态都写到 DSFLOW_HOME/projects/<id>/，项目目录本身不落任何文件。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from ..paths import dsflow_home
from .lifecycle import build_graph
from .schemas import ProjectConfig, Registry
from .validate import ValidationIssue, parse_registry, validate_model

TEXT_SUFFIXES = {
    ".md", ".qmd", ".txt", ".json", ".yaml", ".yml", ".py", ".csv", ".log", ".ipynb", ".toml", ".html",
}
MAX_TEXT_BYTES = 2_000_000
TEXT_LIMITS = {".ipynb": 20_000_000, ".html": 10_000_000}
IMAGE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".svg": "image/svg+xml", ".webp": "image/webp",
}


class ProjectError(Exception):
    pass


def project_id_for(root: Path) -> str:
    # Windows 路径不区分大小写，统一小写后取哈希，保证同一目录只有一个 id
    return hashlib.sha1(str(Path(root).resolve()).lower().encode("utf-8")).hexdigest()[:10]


class Project:
    def __init__(self, root: str | Path, readonly: bool = True):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ProjectError(f"项目目录不存在：{self.root}")
        self.readonly = readonly
        self.id = project_id_for(self.root)
        self.config = self._load_config()

    def _load_config(self) -> ProjectConfig | None:
        path = self.root / "dsflow.yaml"
        if not path.is_file():
            return None
        try:
            return ProjectConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        except Exception as exc:  # noqa: BLE001 — 配置错误统一转成可读提示
            raise ProjectError(f"dsflow.yaml 无法解析：{exc}") from exc

    @property
    def registry_path(self) -> Path:
        return self.root / (self.config.registry if self.config else "lifecycle/steps.json")

    @property
    def name(self) -> str:
        if self.config:
            return self.config.name
        try:
            return self.load_registry_raw().get("title") or self.root.name
        except ProjectError:
            return self.root.name

    @property
    def question(self) -> str:
        return self.config.question if self.config else ""

    def load_registry_raw(self) -> dict:
        path = self.registry_path
        if not path.is_file():
            raise ProjectError(f"未找到步骤注册表：{path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProjectError(f"注册表不是合法 JSON：{exc}") from exc

    def load(self) -> tuple[Registry | None, list[ValidationIssue]]:
        reg, issues = parse_registry(self.load_registry_raw())
        if reg is None:
            return None, issues
        return reg, validate_model(reg, self.root)

    def lifecycle(self) -> dict:
        reg, issues = self.load()
        return {
            "graph": build_graph(reg, self.root) if reg else None,
            "issues": [i.to_dict() for i in issues],
        }

    def state_dir(self) -> Path:
        """平台为本项目保存运行记录、缓存的位置；只读项目放到项目目录之外。"""
        if self.readonly:
            return dsflow_home() / "projects" / self.id
        return self.root / ".dsflow"

    def resolve(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root):
            raise ProjectError("路径越出项目目录")
        return path

    def raw_file(self, rel: str) -> tuple[Path, str]:
        """报告里引用的图片原文件（只允许图片类型）。"""
        path = self.resolve(rel)
        if not path.is_file():
            raise FileNotFoundError(rel)
        media = IMAGE_TYPES.get(path.suffix.lower())
        if media is None:
            raise ProjectError("只能直接读取图片文件")
        return path, media

    def read_text(self, rel: str) -> dict:
        path = self.resolve(rel)
        if not path.is_file():
            raise FileNotFoundError(rel)
        suffix = path.suffix.lower()
        if suffix not in TEXT_SUFFIXES:
            raise ProjectError(f"暂不支持直接读取 {suffix or '无后缀'} 文件")
        size = path.stat().st_size
        if size > TEXT_LIMITS.get(suffix, MAX_TEXT_BYTES):
            raise ProjectError(f"文件过大（{size:,} 字节），不在页面里直接显示")
        return {
            "path": path.relative_to(self.root).as_posix(),
            "size": size,
            "suffix": suffix,
            "content": path.read_text(encoding="utf-8", errors="replace"),
        }
