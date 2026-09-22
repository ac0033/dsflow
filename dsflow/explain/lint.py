"""导读体检：用词、句子是否完整、篇幅、有没有照搬报告。不通过就不许放行（CLI 退出码 1、hook 阻塞）。

分四类：
- **用词**：项目 vocabulary.json 里登记了 avoid 的说法，一律换成登记的词；出现一次就算不通过。
- **句子**：每一句要能单独看懂——以句号结尾、动词带具体宾语、不用口语缩略动词（对上、合上、钉死、站住……）、
  抽象词（口径、主线……）没登记就不能用。规则与原因写在 docs/讲解写法.md。
- **篇幅**：开头六段（背景 / 目的 / 结论 / 操作 / 结果 / 下一步建议）必须齐；结论最多带一个数字；各字段有下限也有上限——
  下限是为了逼出完整的句子（「输出结果讲解」至少 60 字），上限只防止堆砌。
- **照搬**：讲解里出现和本轮报告一模一样的长句，说明是抄过来的，不是讲出来的。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.project import Project
from ..core.schemas import Registry, Revision, Step
from ..core.steps import revision_files, revisions_of
from ..progress.checks import load_vocab
from .guide import load_guide, numbers_in

# 字数上限只防堆砌；下限逼出完整的句子
LIMITS = {"background": 110, "question": 70, "answer": 70, "did": 70, "result": 90, "next": 70}
CELL_LIMITS = {"title": 28, "what": 130, "why": 150, "read": 420}
MIN_LEN = {"what": 18, "why": 18, "read": 60, "answer": 12}
COPIED_RUN = 16  # 和报告一字不差的连续汉字达到这么长，就算照搬

# 口语缩略动词：只有写代码的人自己知道指什么。一出现就退回，右边是该怎么写
CLIPPED = {
    "对上": "核对 A 与 B 是否一致", "对账": "核对 A 与 B 是否一致", "合上": "按 X 列把 A 表和 B 表合并",
    "钉死": "固定 X，不再改动", "定死": "固定 X，不再改动", "写死": "固定 X，不再改动",
    "押在": "主要依赖 X", "压下去": "把 X 降低到 Y", "压到": "把 X 降低到 Y",
    "站住": "在 X 上仍然成立", "站得住": "在 X 上仍然成立", "站不住": "在 X 上不再成立",
    "跑通": "成功执行并得到 X", "露出": "显示 X", "摊开": "逐项列出 X",
    "抹掉": "去掉 X", "堵住": "防止 X", "兜住": "防止 X", "撑着": "由 X 支撑",
    "挑出来": "选出 X", "拍板": "决定 X", "落到": "写入 X", "带进": "记录到 X", "挂上": "关联到 X",
    "上场": "参与 X", "偷看": "使用了不该用的 X", "必输": "误差一定高于 X", "赢在": "在 X 上误差更低",
    "一路成立": "在每个分组都成立", "尺子": "评价方法", "地基": "后续步骤依赖的 X",
}
# 抽象词：没在术语表里解释过就不能用（读者不知道它指的是什么）
ABSTRACT = ("口径", "主线", "闭环", "落盘", "裁判", "门槛")
_END = re.compile(r"[。！？!?]\s*$")
_CONCRETE = re.compile(r"[A-Za-z_][A-Za-z_\-\. ]{2,}|\d|「[^」]+」|『[^』]+』")
_CJK = re.compile(r"[一-鿿]")
_SPLIT = re.compile(r"[，。；：、！？\s（）()「」《》“”\"']+")


class Issue:
    def __init__(self, kind: str, where: str, text: str, fix: str = ""):
        self.kind, self.where, self.text, self.fix = kind, where, text, fix

    def __str__(self) -> str:
        return f"[{self.kind}] {self.where}：{self.text}" + (f" → {self.fix}" if self.fix else "")


# ---------- 遍历导读里的每一段文字 ----------


def texts_of(guide: dict) -> list[tuple[str, str]]:
    """（出处, 文字）。出处写得让人能直接找到该改哪一行。"""
    out: list[tuple[str, str]] = []
    brief = guide.get("brief") or {}
    for key, label in (("background", "背景"), ("question", "目的"), ("answer", "结论"),
                       ("did", "操作"), ("result", "结果"), ("next", "下一步建议")):
        out.append((f"开头 · {label}", brief.get(key) or ""))
    for pi, part in enumerate(guide.get("parts") or [], 1):
        out.append((f"问题 {pi}", part.get("question") or ""))
        out.append((f"问题 {pi} · 答案", part.get("answer") or ""))
        out.append((f"问题 {pi} · 业务含义", part.get("meaning") or ""))
        for ci, note in enumerate(part.get("cells") or [], 1):
            where = f"问题 {pi} · 第 {ci} 条（单元格 {note.get('cell')}）"
            for key in ("title", "what", "why", "read"):
                out.append((f"{where} · {key}", note.get(key) or ""))
            for line in note.get("lines") or []:
                out.append((f"{where} · 第 {line.get('line')} 行的行注", line.get("note") or ""))
            data = note.get("data") or {}
            out.append((f"{where} · 数据视图标题", data.get("title") or ""))
            out.append((f"{where} · 数据视图提醒", data.get("note") or ""))
            for frame in data.get("frames") or []:
                out.append((f"{where} · 数据视图 {frame.get('label')}", frame.get("caption") or ""))
    for i, x in enumerate(guide.get("cannot_say") or [], 1):
        out.append((f"别误读 · 第 {i} 条", x))
    for t in guide.get("terms") or []:
        out.append((f"术语 {t.get('term')}", t.get("plain") or ""))
    return [(w, t) for w, t in out if t]


# ---------- 三类检查 ----------


def _protected(text: str, names: list[str]) -> list[range]:
    """已登记术语在这段文字里占的位置。「订单」要避开，但列名「订单号」是真的，落在它里面的就不算。"""
    spans: list[range] = []
    for name in names:
        start = text.find(name)
        while start >= 0:
            spans.append(range(start, start + len(name)))
            start = text.find(name, start + 1)
    return spans


def check_words(guide: dict, vocab: list[dict]) -> list[Issue]:
    """登记了 avoid 的说法一个都不许出现。术语表自己的解释不查（那里正要说明两者的关系）。"""
    rules = [(bad, t["term"]) for t in vocab for bad in (t.get("avoid") or []) if bad]
    if not rules:
        return []
    # 本步自己登记并解释了的说法也算数：读者能在术语表里查到它，就不是甩出来的黑话
    own = [t["term"] for t in (guide.get("terms") or []) if t.get("term") and t.get("plain")]
    names = sorted({n for t in vocab for n in [t["term"], *(t.get("aliases") or [])]} | set(own), key=len, reverse=True)
    out = []
    for where, text in texts_of(guide):
        if where.startswith("术语 "):
            continue
        spans = _protected(text, names)
        for bad, good in rules:
            at = text.find(bad)
            while at >= 0:
                if not any(at >= s.start and at + len(bad) <= s.stop for s in spans):
                    out.append(Issue("用词", where, f"出现了「{bad}」", f"改成「{good}」"))
                    break
                at = text.find(bad, at + 1)
    return out


def thresholds(project: Project | None) -> dict:
    """字数阈值：模块默认值，被项目 dsflow.yaml 的 guide_lint（limits / cell_limits / min_len）覆盖。"""
    cfg = (project.config.guide_lint if project is not None and project.config else None) or {}
    return {"limits": {**LIMITS, **(cfg.get("limits") or {})},
            "cell_limits": {**CELL_LIMITS, **(cfg.get("cell_limits") or {})},
            "min_len": {**MIN_LEN, **(cfg.get("min_len") or {})}}


def check_length(guide: dict, th: dict | None = None) -> list[Issue]:
    limits = (th or {}).get("limits") or LIMITS
    cell_limits = (th or {}).get("cell_limits") or CELL_LIMITS
    brief = guide.get("brief") or {}
    out = []
    for key, label in (("background", "背景"), ("question", "目的"), ("answer", "结论"),
                       ("did", "操作"), ("result", "结果"), ("next", "下一步建议")):
        value = (brief.get(key) or "").strip()
        if not value:
            out.append(Issue("开头", f"开头 · {label}", "没有写",
                             "开头六段都要有：背景 / 目的 / 结论 / 操作 / 结果 / 下一步建议；结果写这一步留下了哪些核心产出、它们现在能干什么"))
        elif len(value) > limits[key]:
            out.append(Issue("啰嗦", f"开头 · {label}", f"{len(value)} 字", f"控制在 {limits[key]} 字以内"))
    nums = numbers_in(brief.get("answer") or "")
    if len(nums) > 1:
        out.append(Issue("数字", "开头 · 结论", f"有 {len(nums)} 个数字：{'、'.join(nums)}",
                         "结论最多留一个数字，其余放到对应的那一格讲解或数据视图里"))
    if numbers_in(brief.get("did") or ""):
        out.append(Issue("数字", "开头 · 操作", "操作里写了数字", "操作只说做了什么，数字留给讲解"))
    for pi, part in enumerate(guide.get("parts") or [], 1):
        for ci, note in enumerate(part.get("cells") or [], 1):
            for key, cap in cell_limits.items():
                value = (note.get(key) or "").strip()
                if len(value) > cap:
                    out.append(Issue("啰嗦", f"问题 {pi} · 第 {ci} 条 · {key}", f"{len(value)} 字", f"控制在 {cap} 字以内，拆成两格讲"))
            if len(note.get("lines") or []) > 3:
                out.append(Issue("啰嗦", f"问题 {pi} · 第 {ci} 条", f"行注 {len(note['lines'])} 条", "一格最多三条"))
    return out


def _report_text(project: Project, step: Step, rev: Revision) -> str:
    files, _ = revision_files(project.root, rev.dir, exclude_revisions=Path(rev.dir) == Path(step.dir))
    parts = []
    for f in files:
        if f["kind"] not in ("report", "acceptance_report"):
            continue
        try:
            parts.append(project.resolve(f["path"]).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(parts)


def _runs(text: str) -> set[str]:
    """文字里长度达到 COPIED_RUN 的连续汉字片段（去掉标点后再切）。"""
    out = set()
    for chunk in _SPLIT.split(text):
        chunk = "".join(_CJK.findall(chunk))
        for i in range(len(chunk) - COPIED_RUN + 1):
            out.add(chunk[i:i + COPIED_RUN])
    return out


def check_copied(project: Project, step: Step, rev: Revision, guide: dict) -> list[Issue]:
    """讲解要用自己的话讲，不是把报告搬一遍。和报告一字不差的长句直接报出来。"""
    report = _report_text(project, step, rev)
    if not report:
        return []
    from_report = _runs(report)
    out = []
    for where, text in texts_of(guide):
        hit = sorted(_runs(text) & from_report)
        if hit:
            out.append(Issue("照搬", where, f"和本轮报告一字不差：「{hit[0]}…」", "用自己的话讲这一格在做什么"))
    return out


# ---------- 对外 ----------


def _sentence_fields(guide: dict) -> list[tuple[str, str, str]]:
    """（出处, 字段名, 文字）：要按完整句子检查的字段。问题和标题不算——它们本来就是短语。"""
    out: list[tuple[str, str, str]] = []
    brief = guide.get("brief") or {}
    for key, label in (("background", "背景"), ("answer", "结论"), ("did", "操作"), ("result", "结果"), ("next", "下一步建议")):
        out.append((f"开头 · {label}", key, brief.get(key) or ""))
    for pi, part in enumerate(guide.get("parts") or [], 1):
        out.append((f"问题 {pi} · 答案", "answer", part.get("answer") or ""))
        out.append((f"问题 {pi} · 业务含义", "meaning", part.get("meaning") or ""))
        for ci, note in enumerate(part.get("cells") or [], 1):
            where = f"问题 {pi} · 第 {ci} 条（单元格 {note.get('cell')}）"
            for key in ("what", "why", "read"):
                out.append((f"{where} · {key}", key, note.get(key) or ""))
            for line in note.get("lines") or []:
                out.append((f"{where} · 第 {line.get('line')} 行的行注", "note", line.get("note") or ""))
    for i, x in enumerate(guide.get("cannot_say") or [], 1):
        out.append((f"易错点 · 第 {i} 条", "cannot_say", x))
    return [(w, k, t.strip()) for w, k, t in out if t and t.strip()]


def check_sentences(guide: dict, vocab: list[dict] | None = None, th: dict | None = None) -> list[Issue]:
    """每一句要能单独看懂：结尾、缩略动词、抽象词、最短长度、有没有点名具体对象。"""
    from .guide import builtin_terms

    min_len = (th or {}).get("min_len") or MIN_LEN
    known = {t["term"] for t in (vocab or [])} | {t["term"] for t in builtin_terms()}
    known |= {t["term"] for t in (guide.get("terms") or []) if t.get("term")}
    aliases = {a for t in (vocab or []) for a in (t.get("aliases") or [])} | {a for t in builtin_terms() for a in t["aliases"]}
    names = sorted(known | aliases, key=len, reverse=True)
    out: list[Issue] = []
    for where, key, text in _sentence_fields(guide):
        if not _END.search(text):
            out.append(Issue("句子", where, "没有以句号结尾", "写成完整的一句话，以句号收尾"))
        spans = _protected(text, names)
        for bad, good in CLIPPED.items():
            at = text.find(bad)
            while at >= 0:
                if not any(at >= s.start and at + len(bad) <= s.stop for s in spans):
                    out.append(Issue("句子", where, f"用了口语缩略动词「{bad}」", f"写成「{good}」这样带具体宾语的话"))
                    break
                at = text.find(bad, at + 1)
        for word in ABSTRACT:
            if word in text and word not in known and not any(word in n for n in names):
                out.append(Issue("句子", where, f"抽象词「{word}」没有在术语表里解释过", "换成具体对象，或先在 terms 里解释它"))
        if key in min_len and len(text) < min_len[key]:
            out.append(Issue("句子", where, f"只有 {len(text)} 字", f"至少 {min_len[key]} 字：说清对什么、做了什么、结果是什么"))
        if key in ("what", "read") and not _CONCRETE.search(text) and not any(n in text for n in names):
            out.append(Issue("句子", where, "没有点名具体对象", "写出数据表名、列名、文件名、术语或数字，读者才知道在对什么做什么"))
    return out


def lint_guide(project: Project, reg: Registry, step: Step, rev: Revision, guide: dict,
               vocab: list[dict] | None = None) -> list[Issue]:
    vocab = load_vocab(project) or [] if vocab is None else vocab
    th = thresholds(project)
    return [*check_words(guide, vocab), *check_sentences(guide, vocab, th), *check_length(guide, th),
            *check_copied(project, step, rev, guide)]


def lint_project(project: Project, reg: Registry, step_id: str | None = None) -> list[tuple[str, str, list[Issue]]]:
    """（步骤, 轮次, 问题清单）。每一轮都查——历史轮次也有导读，讲的是那一轮为什么返工。"""
    vocab = load_vocab(project) or []
    out = []
    for s in reg.steps:
        if step_id and s.id != step_id:
            continue
        for rev in revisions_of(s):
            guide, error, path, _ = load_guide(project, s, rev)
            if error:
                out.append((s.id, rev.id, [Issue("解析", str(path), error)]))
            elif guide:
                out.append((s.id, rev.id, lint_guide(project, reg, s, rev, guide, vocab)))
    return out
