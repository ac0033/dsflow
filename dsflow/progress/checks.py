"""说明卡与报告的核对：数字核对（从产物重算）与术语检查（不造新概念、说法统一）。"""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path

from ..core.project import Project, ProjectError
from ..core.schemas import Registry
from ..core.steps import load_card, revision_files, revisions_of
from ..data.browse import row_count, run_sql
from ..data.cache import DataCache
from ..data.engine import DataError, connect, ident, scan, slot
from ..data.files import data_format

AGG = {"sum": "sum({})", "count": "count({})", "distinct": "count(DISTINCT {})", "mean": "avg({})",
       "min": "min({})", "max": "max({})"}
_BOLD = re.compile(r"\*\*([^*\n]{1,12})\*\*")
# 报告里 **结论**：… 这类加粗是提示块标签（界面渲染成 Quarto 式提示块），不是术语
CALLOUT_LABELS = {"结论", "结果", "小结", "要点", "核心数字", "发现", "操作", "做法", "方法", "例子", "示例", "注意", "限制", "风险",
                  "易错点", "业务含义", "下一步", "补充", "依据", "证据"}
_PUNCT = re.compile(r"[，。；：、！？,.;:!?（）()《》“”\"'\s\d%％/→—-]")


def parse_number(v) -> tuple[float, int] | None:
    """卡片上的数字 → (数值, 小数位数)。支持千分位逗号和百分号；不是数字返回 None。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return float(v), 0
    s = (repr(v) if isinstance(v, float) else str(v)).strip().replace(",", "").replace("，", "")
    pct = s.endswith("%")
    s = s.rstrip("%")
    try:
        f = float(s)
    except ValueError:
        return None
    dec = len(s.split(".")[1]) if "." in s and "e" not in s.lower() else 0
    return (f / 100, dec + 2) if pct else (f, dec)


def resolve_source(project: Project, rev_dir: str, path_part: str) -> str:
    """出处路径先按本轮目录解析，找不到再按项目根目录解析。"""
    for candidate in (posixpath.normpath(posixpath.join(rev_dir, path_part)), posixpath.normpath(path_part)):
        try:
            if project.resolve(candidate).is_file():
                return candidate
        except ProjectError:
            continue
    raise FileNotFoundError(path_part)


def read_value(project: Project, rel: str, selector: str) -> float:
    path = project.resolve(rel)
    sel = selector.strip()
    if path.suffix.lower() == ".json":
        node = json.loads(path.read_text(encoding="utf-8"))
        for part in [p.replace("~1", "/").replace("~0", "~") for p in sel.strip("/").split("/") if p]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        return float(node)
    if data_format(path) is None:
        raise DataError(f"不支持从 {path.suffix} 文件取值")
    parquet = DataCache(project).prepare(rel)
    if sel == "rows":
        return float(row_count(parquet))
    if sel.startswith("sql:"):
        result = run_sql(parquet, sel[4:], limit=1)
        if not result["rows"]:
            raise DataError("查询没有返回结果")
        return float(result["rows"][0][1])
    fn, _, column = sel.partition(":")
    if fn in AGG and column:
        return float(connect().execute(f"SELECT {AGG[fn].format(ident(column))} FROM {scan(parquet)}").fetchone()[0])
    raise DataError(f"不认识的取值方式：{selector}")


def check_number(project: Project, rev_dir: str, num: dict) -> dict:
    out = {"label": num["label"], "expected": num.get("after"), "source": num.get("source")}
    if not num.get("source"):
        return {**out, "status": "no_source", "detail": "没有写出处，无法核对"}
    expected = parse_number(num.get("after"))
    if expected is None:
        return {**out, "status": "error", "detail": "「处理后」不是数字，无法核对"}
    path_part, _, selector = num["source"].partition("#")
    try:
        rel = resolve_source(project, rev_dir, path_part)
        with slot():
            actual = read_value(project, rel, selector or "rows")
    except FileNotFoundError:
        return {**out, "status": "error", "detail": f"出处文件不存在：{path_part}"}
    except Exception as exc:  # noqa: BLE001 — 取值失败如实报告
        return {**out, "status": "error", "detail": f"取值失败：{str(exc).splitlines()[0]}"}
    value, dec = expected
    match = abs(round(actual, dec) - round(value, dec)) <= 10 ** (-dec) / 2 + 1e-9
    return {**out, "actual": actual, "status": "match" if match else "mismatch",
            "detail": f"按卡片写的 {dec} 位小数比较" if dec else "按整数比较"}


def _read_vocab(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    terms = data.get("terms", []) if isinstance(data, dict) else data
    return [t for t in terms if isinstance(t, dict) and t.get("term")]


def load_vocab(project: Project) -> list[dict] | None:
    """项目自带的术语表 + 平台目录里的那份。只读项目改不了项目目录，术语就登记在平台目录。"""
    name = project.config.vocabulary if project.config else "vocabulary.json"
    terms = _read_vocab(project.root / name)
    seen = {t["term"] for t in terms}
    terms += [t for t in _read_vocab(project.state_dir() / "vocabulary.json") if t["term"] not in seen]
    return terms or None


def check_terms(text: str, vocab: list[dict]) -> dict:
    """不推荐的同义说法（应统一成登记的术语）与未登记的加粗短词（可能是新造的概念）。"""
    known = {t["term"] for t in vocab}
    flagged = {bad for t in vocab for bad in t.get("avoid", [])}
    avoid = []
    for t in vocab:
        for bad in t.get("avoid", []):
            n = text.count(bad)
            if bad and n:
                avoid.append({"found": bad, "use": t["term"], "count": n})
    unregistered = sorted({
        m for m in _BOLD.findall(text)
        if not _PUNCT.search(m) and m not in known | flagged | CALLOUT_LABELS and not any(k in m for k in known)
    })[:20]
    return {"avoid": avoid, "unregistered": unregistered}


def _card_text(card: dict) -> str:
    parts = [card.get("headline", ""), card.get("operation", ""), card.get("why", ""), card.get("concentration", ""),
             card.get("next", ""), *card.get("exceptions", []), *card.get("invariants", []), *card.get("can_say", []),
             *card.get("cannot_say", [])]
    for ex in card.get("examples", []):
        parts += [ex.get("input", ""), ex.get("rule", ""), ex.get("output", "")]
    return "\n".join(parts)


def step_checks(project: Project, reg: Registry, step_id: str, vocab: list[dict] | None = None) -> dict:
    step = next((s for s in reg.steps if s.id == step_id), None)
    if step is None:
        raise KeyError(step_id)
    revs = revisions_of(step)
    rev = next((r for r in revs if r.id == step.current_revision), revs[-1])
    card, card_error = load_card(project.root, rev.dir)
    numbers = [check_number(project, rev.dir, n) for n in (card or {}).get("core_numbers", [])]
    texts = [_card_text(card)] if card else []
    files, _ = revision_files(project.root, rev.dir, exclude_revisions=Path(rev.dir) == Path(step.dir))
    for f in files:
        if f["kind"] == "report" and f["path"].endswith((".md", ".qmd")) and f["size"] < 2_000_000:
            texts.append((project.root / f["path"]).read_text(encoding="utf-8", errors="replace"))
    return {
        "step": step_id, "revision": rev.id, "has_card": card is not None, "card_error": card_error,
        "numbers": {
            "items": numbers,
            "checked": sum(1 for n in numbers if n["status"] in ("match", "mismatch")),
            "matched": sum(1 for n in numbers if n["status"] == "match"),
            "total": len(numbers),
        },
        "vocabulary": vocab is not None,
        "terms": check_terms("\n".join(texts), vocab) if vocab is not None and texts else None,
    }


def project_checks(project: Project, reg: Registry) -> list[dict]:
    vocab = load_vocab(project)
    return [step_checks(project, reg, s.id, vocab) for s in reg.steps]
