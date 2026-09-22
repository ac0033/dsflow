"""notebook 导读（guide.yaml）：逐格讲清 notebook 在做什么、为什么这样做、输出怎么读。

读者是懂业务、懂技术原理、能读代码，但没做过数据科学的负责人：讲解围绕 notebook 里真实的单元格与输出，
不复述用户报告；术语用白话解释（内置术语表 + 项目 vocabulary.json + 本步自己登记的说法）。

存放：可写项目放在轮次目录下的 guide.yaml；只读项目放在 DSFLOW_HOME/projects/<id>/guides/<步骤>/<轮次>.yaml，
项目目录里绝不写入。核对：引用的 notebook、单元格、行号都要存在；讲解里写的数字要能在所引用单元格的代码或输出里找到。
"""

from __future__ import annotations

import json
import posixpath
import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from ..core.project import Project, ProjectError
from ..core.schemas import Guide, Registry, Revision, Step
from ..core.steps import revision_files, revisions_of
from ..progress.checks import load_vocab

GUIDE_NAME = "guide.yaml"
GLOSSARY_FILE = Path(__file__).with_name("glossary.yaml")
PLACEHOLDER = "待填"


class GuideError(Exception):
    pass


# ---------- 定位步骤、轮次与导读文件 ----------


def find_step(reg: Registry, step_id: str) -> Step:
    step = next((s for s in reg.steps if s.id == step_id), None)
    if step is None:
        raise KeyError(f"步骤 {step_id} 不存在")
    return step


def pick_revision(step: Step, rev_id: str | None = None) -> Revision:
    revs = revisions_of(step)
    if rev_id is None:
        return next((r for r in revs if r.id == step.current_revision), revs[-1])
    rev = next((r for r in revs if r.id == rev_id), None)
    if rev is None:
        raise KeyError(f"步骤 {step.id} 没有轮次 {rev_id}")
    return rev


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name)


def guide_paths(project: Project, rev: Revision, step_id: str) -> tuple[Path, Path]:
    """（轮次目录里的导读，平台目录里的导读）。读取时项目自带的优先；只读项目只能写平台目录。"""
    return (project.root / rev.dir / GUIDE_NAME,
            project.state_dir() / "guides" / _safe(step_id) / f"{_safe(rev.id)}.yaml")


def write_target(project: Project, rev: Revision, step_id: str) -> Path:
    in_rev, in_state = guide_paths(project, rev, step_id)
    return in_state if project.readonly else in_rev


# ---------- notebook ----------


def _text(value) -> str:
    return "".join(value) if isinstance(value, list) else (value or "")


def read_cells(path: Path) -> list[dict]:
    """notebook → 每格 {type, source, output}；output 是这一格全部输出的文字形式，用于数字核对。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GuideError(f"notebook 无法读取：{path.name}（{exc}）") from exc
    return cells_from_text(text, path.name)


def cells_from_text(text: str, name: str = "notebook") -> list[dict]:
    """同 read_cells，但直接吃 notebook 的文本内容（答疑要讲的 notebook 已经在内存里了）。"""
    try:
        nb = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GuideError(f"notebook 无法读取：{name}（{exc}）") from exc
    cells = []
    for cell in nb.get("cells", []):
        texts = []
        for out in cell.get("outputs") or []:
            kind = out.get("output_type")
            if kind == "stream":
                texts.append(_text(out.get("text")))
            elif kind == "error":
                texts.append(f"{out.get('ename')}: {out.get('evalue')}\n" + "\n".join(out.get("traceback") or []))
            else:
                data = out.get("data") or {}
                texts.append(_text(data.get("text/plain")) or re.sub(r"<[^>]+>", " ", _text(data.get("text/html"))))
        cells.append({"type": cell.get("cell_type", ""), "source": _text(cell.get("source")),
                      "output": "\n".join(t for t in texts if t)})
    return cells


def notebooks_of(project: Project, step: Step, rev: Revision) -> list[str]:
    """本轮能讲的 notebook（项目内相对路径）：注册表登记的排在前面，其余按路径排序。"""
    files, _ = revision_files(project.root, rev.dir, exclude_revisions=Path(rev.dir) == Path(step.dir))
    found = [f["path"] for f in files if f["kind"] == "notebook"]
    registered = [p for p in (step.execution_notebooks or []) if p in found]
    return [*registered, *[p for p in found if p not in registered]]


def resolve_notebook(project: Project, rev_dir: str, ref: str) -> str | None:
    """导读里写的 notebook 路径：先按本轮目录解析，再按项目根目录。"""
    for candidate in (posixpath.normpath(posixpath.join(rev_dir, ref)), posixpath.normpath(ref)):
        try:
            if project.resolve(candidate).is_file():
                return candidate
        except ProjectError:
            continue
    return None


# ---------- 数字核对 ----------

_DATETIME = re.compile(r"\d{4}-\d{1,2}(?:-\d{1,2})?|\d{1,2}:\d{2}(?::\d{2})?")
_NUMBER = re.compile(r"(?<![A-Za-z_\d.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(%|％)?(?![A-Za-z_\d])")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


def numbers_in(text: str, skip: set[str] = frozenset()) -> list[str]:
    """讲解里出现的、值得回到输出里核对的数字。日期、时间、个位数和步骤编号不算。"""
    out: list[str] = []
    for m in _NUMBER.finditer(_DATETIME.sub(" ", text or "")):
        whole, frac, pct = m.group(1), m.group(2) or "", m.group(3) or ""
        plain = whole.replace(",", "") + frac
        if plain in skip or (not frac and not pct and int(whole.replace(",", "")) < 10):
            continue
        out.append(m.group(0))
    return out


def _forms(raw: str) -> list[str]:
    """一个数字在输出里可能的写法：22.73% 也可能印成 0.2273。"""
    value = raw.replace(",", "").rstrip("%％")
    if raw[-1] not in "%％":
        return [value]
    dec = len(value.split(".")[1]) if "." in value else 0
    return [value, f"{float(value) / 100:.{dec + 2}f}"]


def found_in(raw: str, haystack: str) -> bool:
    for form in _forms(raw):
        tail = r"(?:\.0+)?" if "." not in form else ""
        if re.search(r"(?<![\d.])" + re.escape(form) + tail + r"(?!\.?\d)", haystack):
            return True
    return False


def _haystack(cells: list[dict], index: list[int]) -> str:
    text = "\n".join(f"{cells[i - 1]['source']}\n{cells[i - 1]['output']}" for i in index)
    return _THOUSANDS.sub("", text)


def _indexes(cell) -> list[int]:
    return [int(c) for c in (cell if isinstance(cell, list) else [cell])]


def check_guide(project: Project, reg: Registry, step: Step, rev: Revision, guide: dict) -> dict:
    """核对导读：引用的单元格和行存在；讲解里的数字能在所引用单元格的代码或输出里找到。"""
    errors: list[str] = []
    missing: list[dict] = []
    checked = 0
    skip = {s.id for s in reg.steps}
    loaded: dict[str, list[dict]] = {}

    def cells_of(ref: str, where: str) -> list[dict] | None:
        if ref not in loaded:
            path = resolve_notebook(project, rev.dir, ref)
            if path is None:
                errors.append(f"{where}：找不到 notebook {ref}")
                loaded[ref] = []
            else:
                try:
                    loaded[ref] = read_cells(project.resolve(path))
                except GuideError as exc:
                    errors.append(f"{where}：{exc}")
                    loaded[ref] = []
        return loaded[ref] or None

    def count(text: str, where: str, part: int | None, cell: int | None, hay: str) -> None:
        nonlocal checked
        for raw in numbers_in(text, skip):
            checked += 1
            if not found_in(raw, hay):
                missing.append({"where": where, "part": part, "cell": cell, "number": raw})

    default_nb = guide.get("notebook") or (notebooks_of(project, step, rev) or [None])[0]
    all_text: list[str] = []
    for pi, part in enumerate(guide.get("parts") or []):
        part_nb = part.get("notebook") or default_nb
        part_text: list[str] = []
        for ci, note in enumerate(part.get("cells") or []):
            where = f"问题 {pi + 1} · 第 {ci + 1} 条"
            ref = note.get("notebook") or part_nb
            if not ref:
                errors.append(f"{where}：没有写 notebook，本轮也没有找到 notebook")
                continue
            cells = cells_of(ref, where)
            if cells is None:
                continue
            index = _indexes(note["cell"])
            bad = [i for i in index if not 1 <= i <= len(cells)]
            if bad:
                errors.append(f"{where}：{Path(ref).name} 只有 {len(cells)} 个单元格，没有第 {'、'.join(map(str, bad))} 个")
                continue
            for line in note.get("lines") or []:
                target = line.get("cell") or index[0]
                if target not in index:
                    errors.append(f"{where}：行注写的单元格 {target} 不在这条讲解引用的单元格里")
                    continue
                total = len(cells[target - 1]["source"].splitlines())
                if not 1 <= line["line"] <= total:
                    errors.append(f"{where}：单元格 {target} 只有 {total} 行，没有第 {line['line']} 行")
            hay = _haystack(cells, index)
            part_text.append(hay)
            for field in ("what", "read"):
                count(note.get(field) or "", where, pi, ci, hay)
            for line in note.get("lines") or []:
                count(line.get("note") or "", where, pi, ci, hay)
        joined = "\n".join(part_text)
        all_text.append(joined)
        count(part.get("answer") or "", f"问题 {pi + 1} 的答案", pi, None, joined)

    # 开头四段概括的是整步，允许引用 notebook 里任何一格的输出
    whole = []
    for ref in dict.fromkeys([r for r in [default_nb, *loaded] if r]):
        cells = cells_of(ref, "开头")
        if cells:
            whole.append(_haystack(cells, list(range(1, len(cells) + 1))))
    brief_hay = "\n".join(whole) or "\n".join(all_text)
    brief = guide.get("brief") or {}
    count(brief.get("answer") or "", "结论", None, None, brief_hay)
    errors += check_data(project, guide)

    return {"errors": errors, "checked": checked, "found": checked - len(missing), "missing": missing}


def check_data(project: Project, guide: dict) -> list[str]:
    """核对数据视图：写的文件要真的在、写的列要真的有、要点亮的列要在这一屏里。只读一行，不建缓存。"""
    from ..data.engine import DataError
    from ..data.peek import peek

    out: list[str] = []
    for pi, part in enumerate(guide.get("parts") or []):
        for ci, note in enumerate(part.get("cells") or []):
            data = note.get("data")
            if not data:
                continue
            where = f"问题 {pi + 1} · 第 {ci + 1} 条的数据视图"
            marks = [line["mark"] for line in (note.get("lines") or []) if line.get("mark")]
            for frame in data.get("frames") or []:
                try:
                    got = peek(project, frame["file"], frame.get("columns") or [], 1, frame.get("sheet", 0))
                except FileNotFoundError:
                    out.append(f"{where}：找不到数据文件 {frame['file']}")
                    continue
                except (DataError, ProjectError) as exc:
                    out.append(f"{where}（{frame['file']}）：{exc}")
                    continue
                have = set(got["columns"])
                for mark in [frame.get("mark"), *marks]:
                    bad = [c for c in (mark or {}).get("columns") or [] if c not in have]
                    if bad:
                        out.append(f"{where}：{frame['label']} 这一屏里没有要点亮的列 {'、'.join(bad)}")
    return out


# ---------- 术语 ----------


@lru_cache(maxsize=1)
def builtin_terms() -> tuple[dict, ...]:
    data = yaml.safe_load(GLOSSARY_FILE.read_text(encoding="utf-8")) or []
    return tuple({"term": t["term"], "plain": t["plain"], "aliases": list(t.get("aliases") or []), "source": "内置"}
                 for t in data)


def terms_for(project: Project, guide: dict | None) -> list[dict]:
    """本步能用到的术语：本步登记的 > 项目术语表 > 平台内置。"""
    items = [
        *({"term": t["term"], "plain": t.get("plain", ""), "aliases": list(t.get("aliases") or []), "source": "本步"}
          for t in (guide or {}).get("terms") or []),
        *({"term": t["term"], "plain": t.get("meaning", ""), "aliases": [], "source": "项目"}
          for t in load_vocab(project) or []),
        *builtin_terms(),
    ]
    out: list[dict] = []
    seen: set[str] = set()
    for t in items:
        if t["term"] in seen or not t["plain"]:
            continue
        seen.add(t["term"])
        out.append(t)
    return out


# ---------- 读取与展示 ----------


def load_guide(project: Project, step: Step, rev: Revision) -> tuple[dict | None, str | None, Path | None, str]:
    """返回（导读, 解析错误, 文件路径, 存放位置）。项目自带的 guide.yaml 优先于平台目录里的。"""
    in_rev, in_state = guide_paths(project, rev, step.id)
    for path, where in ((in_rev, "revision"), (in_state, "platform")):
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return Guide.model_validate(data).model_dump(), None, path, where
        except (yaml.YAMLError, ValidationError, OSError) as exc:
            return None, "导读无法解析：" + " ".join(str(exc).split("\n")[:3]), path, where
    return None, None, None, ""


def _display(project: Project, path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.relative_to(project.root).as_posix()
    except ValueError:
        return f"平台目录/{path.relative_to(project.state_dir()).as_posix()}"


def guide_view(project: Project, reg: Registry, step_id: str, rev_id: str | None = None) -> dict:
    """步骤页「讲解」要的全部内容：导读、可讲的 notebook、核对结果、术语。没有导读时也给出该写到哪。"""
    step = find_step(reg, step_id)
    rev = pick_revision(step, rev_id)
    guide, error, path, where = load_guide(project, step, rev)
    notebooks = notebooks_of(project, step, rev)
    primary = guide.get("notebook") if guide else None
    return {
        "step": step.id,
        "revision": rev.id,
        "notebooks": notebooks,
        "notebook": (resolve_notebook(project, rev.dir, primary) if primary else None) or (notebooks[0] if notebooks else None),
        "revision_dir": rev.dir,
        "guide": guide,
        "error": error,
        "source": _display(project, path),
        "stored_in": where,
        "target": _display(project, write_target(project, rev, step.id)),
        "readonly": project.readonly,
        "checks": check_guide(project, reg, step, rev, guide) if guide else None,
        "terms": terms_for(project, guide),
    }


def brief_of(project: Project, step: Step) -> dict | None:
    """流程图节点、阶段概况、看板上用的讲解开头：当前轮次导读的 背景 / 目的 / 结论 / 能否继续 / 下一步。

    有导读就用导读（讲给人听的话），没有才让页面退回注册表原话——退回时页面要标明是原话。
    """
    try:
        rev = pick_revision(step)
    except KeyError:
        return None
    guide, _, _, _ = load_guide(project, step, rev)
    if not guide:
        return None
    b = guide.get("brief") or {}
    return {"revision": rev.id, "background": b.get("background") or "", "question": b.get("question") or "",
            "answer": b.get("answer") or "", "can_continue": b.get("can_continue"), "did": b.get("did") or "",
            "result": b.get("result") or "", "next": b.get("next") or "", "parts": len(guide.get("parts") or [])}


def attach_briefs(project: Project, reg: Registry, graph: dict) -> dict:
    """给流程图的每个节点挂上讲解开头（brief），没有导读的节点是 None。"""
    by_id = {s.id: s for s in reg.steps}
    for node in graph.get("nodes") or []:
        step = by_id.get(node.get("id"))
        node["brief"] = brief_of(project, step) if step else None
    return graph


# ---------- 生成骨架与写入 ----------


def _first_line(source: str) -> str:
    for line in source.splitlines():
        if line.strip():
            return line.strip()[:60]
    return "（空）"


def scaffold(project: Project, reg: Registry, step_id: str, rev_id: str | None = None,
             notebook: str | None = None) -> str:
    """按 notebook 的真实单元格生成导读骨架：每一格列出行数与第一行，讲解内容由 agent 填。"""
    step = find_step(reg, step_id)
    rev = pick_revision(step, rev_id)
    found = notebooks_of(project, step, rev)
    ref = notebook or (found[0] if found else None)
    if ref is None:
        raise GuideError(f"{step.id} {rev.id} 本轮目录里没有 notebook，无法生成导读骨架")
    path = resolve_notebook(project, rev.dir, ref)
    if path is None:
        raise GuideError(f"找不到 notebook：{ref}")
    rel = posixpath.relpath(path, rev.dir)
    cells = read_cells(project.resolve(path))
    lines = [
        f"# {step.id} {step.title} · {rev.id} 的 notebook 导读（写法见 docs/agent-guide.md 与 docs/讲解写法.md）",
        "# 读者：懂业务、懂技术原理、能读代码，但没做过数据科学的负责人。",
        "# 每一句要能单独看懂：动词带具体宾语（表名、列名、文件、术语、数字），以句号结尾，不用口语缩略动词。",
        "# 只讲这个 notebook 里真实的单元格和输出，不复述用户报告；数字照输出原样写，平台会逐个回到输出里核对。",
        f'step: "{step.id}"',
        f"revision: {rev.id}",
        f"notebook: {rel}",
        "brief:                              # 开头六段：背景 / 目的 / 结论 / 操作 / 结果 / 下一步建议",
        f"  background: {PLACEHOLDER}        # 背景：为什么要有这一步、和上一步什么关系",
        f"  question: {PLACEHOLDER}          # 目的：这一步要回答什么，一句业务的话",
        f"  answer: {PLACEHOLDER}            # 结论：回答上面那个问题，一句，最多带一个数字",
        "  can_continue: null               # 能不能往下走",
        f"  did: {PLACEHOLDER}               # 操作：做了什么，一句白话，不写数字",
        f"  result: {PLACEHOLDER}            # 结果：做完留下了哪些核心产出、它们现在能干什么（和目的、操作对得上）",
        f"  next: {PLACEHOLDER}              # 下一步建议：接下来该做什么、可以不做什么",
        "parts:",
        f"  - question: {PLACEHOLDER}        # 读者要弄明白的一个问题；一份导读一般 1～3 个",
        '    answer: ""',
        '    meaning: ""                     # 业务含义',
        "    cells:",
    ]
    for i, cell in enumerate(cells, 1):
        kind = "说明" if cell["type"] == "markdown" else "代码"
        rows = len(cell["source"].splitlines())
        lines.append(f"      # 单元格 {i}（{kind}，{rows} 行）：{_first_line(cell['source'])}")
        if cell["type"] == "code":
            lines += [f"      - cell: {i}", '        what: ""   # 做什么：对哪份数据的哪几列做了什么操作',
                      '        why: ""    # 为什么：不这样做会出什么问题',
                      '        read: ""   # 输出结果讲解（至少 60 字）：指着输出里的数字说它是什么、和预期或上一步比怎么样、说明了什么']
    lines += ["terms: []", "cannot_say: []", ""]
    return "\n".join(lines)


def validate_text(text: str) -> dict:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise GuideError(f"不是合法的 YAML：{exc}") from exc
    try:
        return Guide.model_validate(data).model_dump()
    except ValidationError as exc:
        raise GuideError(f"导读字段不合规：{exc}") from exc


def put_guide(project: Project, reg: Registry, step_id: str, text: str, rev_id: str | None = None) -> tuple[Path, dict]:
    """把写好的导读放到平台读得到的位置（只读项目放平台目录），并立即核对一次。"""
    step = find_step(reg, step_id)
    rev = pick_revision(step, rev_id)
    guide = validate_text(text)
    if guide["step"] != step.id:
        raise GuideError(f"导读里写的 step 是 {guide['step']}，与 {step.id} 不一致")
    target = write_target(project, rev, step.id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return target, check_guide(project, reg, step, rev, guide)
