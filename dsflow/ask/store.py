"""问答与标注的存档：一行一条 JSON，按步骤分文件，放在平台目录里。

放平台目录（`<DSFLOW_HOME>/projects/<id>/asks/` 或项目内 `.dsflow/asks/`）有两个原因：
只读项目一个字也不能往项目目录里写；问答是"我这个人看的时候问的"，不属于交给下一个 agent 的项目文件。
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..core.project import Project

PROJECT_LEVEL = "_project"  # 不针对某一步的提问存在这个文件里
MAX_PER_STEP = 500


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name) or PROJECT_LEVEL


@dataclass
class Record:
    """一条问答：问了什么、引的是哪句话、答的是什么、有没有钉在页面上。"""

    id: str
    at: float
    question: str
    answer: str = ""
    step: str = ""
    rev: str = ""
    tab: str = ""
    file: str = ""
    quote: str = ""
    notes: list[dict] = field(default_factory=list)  # 一次问多处时，每处的原文与用户自己写的备注：{quote, note}
    mark: bool = False               # 钉在页面上：引的那句话会一直高亮，点开就是这条问答
    model: str = ""
    tools: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)  # 答案里没能在上下文或工具返回里找到出处的数字
    links: list[dict] = field(default_factory=list)      # 答案里提到、项目里确实有的东西：数据文件、代码、notebook 的某一格
    saved_term: str = ""             # 已经收进术语表的词
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class AskStore:
    def __init__(self, project: Project):
        self.dir = project.state_dir() / "asks"

    def _path(self, step: str | None) -> Path:
        return self.dir / f"{_safe(step or PROJECT_LEVEL)}.jsonl"

    def _read(self, path: Path) -> list[Record]:
        if not path.is_file():
            return []
        out: list[Record] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue  # 半行坏数据不能让整页打不开
            known = {k: v for k, v in data.items() if k in Record.__dataclass_fields__}
            out.append(Record(**known))
        return out

    def _write(self, path: Path, records: list[Record]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n" for r in records[-MAX_PER_STEP:])
        tmp = path.with_suffix(f".jsonl.tmp{os.getpid()}")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)  # 先写临时文件再替换：写一半崩溃也不会留下半条记录

    def new_id(self) -> str:
        return f"q{int(time.time() * 1000):x}"

    def list(self, step: str | None = None, rev: str | None = None) -> list[Record]:
        """某一步的问答（按时间正序）；step 省略时给项目层那份。"""
        items = self._read(self._path(step))
        if rev:
            items = [r for r in items if not r.rev or r.rev == rev]
        return items

    def add(self, record: Record) -> Record:
        path = self._path(record.step or None)
        items = self._read(path)
        items.append(record)
        self._write(path, items)
        return record

    def update(self, record_id: str, step: str | None, **patch) -> Record | None:
        path = self._path(step)
        items = self._read(path)
        for i, r in enumerate(items):
            if r.id == record_id:
                items[i] = Record(**{**r.to_dict(), **patch})
                self._write(path, items)
                return items[i]
        return None

    def delete(self, record_id: str, step: str | None) -> bool:
        path = self._path(step)
        items = self._read(path)
        kept = [r for r in items if r.id != record_id]
        if len(kept) == len(items):
            return False
        self._write(path, kept)
        return True
