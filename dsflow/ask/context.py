"""模型看到的上下文：用户此刻在看哪一页、选中了哪一句、这句话周围的原文、能用上的术语。

只喂当前这一屏的东西，不把整个项目倒给模型；要看别处，模型自己调只读工具（`tools.READONLY`）。
组装出来的 `sources` 还有第二个用处：答完以后拿它核对答案里的数字有没有出处，和讲解的数字核对同一套办法。
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field

from ..core.project import Project, ProjectError
from ..core.schemas import STATUS_LABEL, Registry
from ..explain.guide import GuideError, brief_of, cells_from_text, find_step, load_guide, pick_revision, terms_for

TAB_LABEL = {
    "guide": "讲解", "board": "看板", "data": "数据", "plan": "执行计划", "code": "代码",
    "log": "执行日志", "products": "产物", "flow": "流程图", "tracker": "问题与决策",
    "runs": "运行与实验", "models": "模型与交付", "overview": "总览",
}
EXCERPT = 4000   # 引文周围最多带多少字
AROUND = 1500    # 选中那句话前后各留多少字
MAX_TERMS = 40
MAX_NOTES = 12   # 一次提问最多带几处标注
NOTE_LEN = 800   # 单处标注的原文与备注各留多少字


@dataclass
class Scope:
    """用户提问时停在哪里。"""

    step: str | None = None
    rev: str | None = None
    tab: str | None = None
    file: str | None = None
    quote: str = ""
    notes: list[dict] = field(default_factory=list)  # 先在页面上标注、攒着一起问的几处：{quote, note}
    mark: bool = False                               # 答完把问过的那几句钉在页面上

    @classmethod
    def from_dict(cls, data: dict) -> Scope:
        notes: list[dict] = []
        for item in (data.get("notes") or [])[:MAX_NOTES]:
            quote = (item.get("quote") or "").strip()[:NOTE_LEN]
            if quote:
                notes.append({"quote": quote, "note": (item.get("note") or "").strip()[:NOTE_LEN]})
        return cls(step=data.get("step") or None, rev=data.get("rev") or None, tab=data.get("tab") or None,
                   file=data.get("file") or None, quote=(data.get("quote") or "").strip(), notes=notes,
                   mark=bool(data.get("mark")))

    @property
    def pinned(self) -> bool:
        """这一问答完要不要钉在页面上：标注过的几处一定钉住，单句要用户自己勾。"""
        return bool(self.notes) or (self.mark and bool(self.quote))

    @property
    def anchor(self) -> str:
        """这一屏的原文以哪一句为中心切出来：优先用户选中的那句，其次第一处标注。"""
        return self.quote or (self.notes[0]["quote"] if self.notes else "")


@dataclass
class Context:
    text: str                       # 拼给模型的那段话
    sources: str                    # 数字核对的底稿：引文、原文片段、讲解开头
    terms: list[dict] = field(default_factory=list)
    file: str | None = None


def _excerpt(content: str, quote: str) -> str:
    """引文周围的原文。没有引文就取开头；有引文就以它为中心切一段，并按整行对齐。"""
    if len(content) <= EXCERPT:
        return content
    at = content.find(quote) if quote else -1
    if at < 0:
        return content[:EXCERPT] + "\n……（后面还有，需要就用 file_read 读全文）"
    start = max(0, at - AROUND)
    end = min(len(content), at + len(quote) + AROUND)
    start = content.rfind("\n", 0, start) + 1 if start else 0
    tail = content.find("\n", end)
    end = tail if tail > 0 else end
    head = "……（前面还有）\n" if start else ""
    return head + content[start:end] + ("\n……（后面还有）" if end < len(content) else "")


def _notebook_text(content: str, quote: str) -> str:
    """notebook 按单元格摊平：第几格、代码、输出，这样模型指得出是哪一格。"""
    try:
        cells = cells_from_text(content)
    except GuideError:
        return _excerpt(content, quote)
    blocks = []
    for i, cell in enumerate(cells, 1):
        kind = "说明" if cell["type"] == "markdown" else "代码"
        out = cell["output"].strip()
        blocks.append(f"[单元格 {i}·{kind}]\n{cell['source'].strip()}"
                      + (f"\n[输出]\n{out[:1200]}" if out else ""))
    return _excerpt("\n\n".join(blocks), quote)


def _file_text(project: Project, rel: str, quote: str) -> tuple[str, str]:
    """（给模型看的片段，文件说明）。读不出来就说明读不出来，不编。"""
    try:
        data = project.read_text(rel)
    except (FileNotFoundError, ProjectError) as exc:
        return "", f"（{rel} 读不出来：{exc}）"
    content = data["content"]
    body = _notebook_text(content, quote) if rel.endswith(".ipynb") else _excerpt(content, quote)
    return body, f"文件 {rel}（{data['size']} 字节）"


def _used_terms(terms: list[dict], text: str) -> list[dict]:
    """只带真正出现在这一屏里的术语，外加本步自己登记的那几个。"""
    out, seen = [], set()
    for t in terms:
        names = [t["term"], *(t.get("aliases") or [])]
        if t["term"] in seen:
            continue
        if t.get("source") == "本步" or any(n and n in text for n in names):
            seen.add(t["term"])
            out.append(t)
        if len(out) >= MAX_TERMS:
            break
    return out


def build(project: Project, reg: Registry | None, scope: Scope) -> Context:
    """把当前这一屏拼成一段话交给模型。"""
    lines: list[str] = [f"项目：{project.name}（平台 id {project.id}）。"]
    if project.question:
        lines.append(f"项目要回答的问题：{project.question}")
    sources: list[str] = []
    terms: list[dict] = []
    guide = None

    step = None
    if reg is not None and scope.step:
        try:
            step = find_step(reg, scope.step)
        except KeyError:
            step = None
    if step is not None:
        rev = pick_revision(step, scope.rev if scope.rev else None) if scope.rev or step.current_revision else None
        guide, _, _, _ = load_guide(project, step, rev) if rev else (None, None, None, "")
        lines.append(f"用户正在看：步骤 {step.id} {step.title}，状态「{STATUS_LABEL.get(step.status, step.status)}」"
                     + (f"，轮次 {rev.id}" if rev else "") + (f"，选项卡「{TAB_LABEL.get(scope.tab, scope.tab)}」" if scope.tab else "") + "。")
        brief = brief_of(project, step)
        if brief:
            head = "；".join(f"{k}：{brief[v]}" for k, v in
                            (("背景", "background"), ("目的", "question"), ("结论", "answer"), ("操作", "did"), ("结果", "result"), ("下一步", "next")) if brief.get(v))
            if head:
                lines.append(f"这一步的讲解开头——{head}")
                sources.append(head)
        elif step.op:
            lines.append(f"这一步登记的目的：{step.op}")
    elif scope.tab:
        lines.append(f"用户正在看：项目层的「{TAB_LABEL.get(scope.tab, scope.tab)}」。")

    excerpt = ""
    if scope.file:
        excerpt, note = _file_text(project, scope.file, scope.anchor)
        lines.append(f"这一屏的原文来自 {note}。")
        if excerpt:
            lines.append("原文片段：\n```\n" + excerpt + "\n```")
            sources.append(excerpt)

    if scope.quote:
        lines.append(f"用户选中的是这一句：\n「{scope.quote}」")
        sources.append(scope.quote)

    if scope.notes:
        lines.append(f"用户在这一屏上先标注了 {len(scope.notes)} 处，再一起提问；请按同样的序号逐处回答：")
        for i, item in enumerate(scope.notes, 1):
            mine = f"；他在这一处写的备注是：{item['note']}" if item["note"] else "；他在这一处没有写备注。"
            lines.append(f"{i}. 原文「{item['quote']}」{mine}")
            sources.append(item["quote"])

    marked = "\n".join(item["quote"] + "\n" + item["note"] for item in scope.notes)
    terms = _used_terms(terms_for(project, guide), (scope.quote or "") + "\n" + marked + "\n" + excerpt)
    if terms:
        lines.append("平台已登记的术语（解释要和它们一致，别换说法）：\n"
                     + "\n".join(f"- {t['term']}：{t['plain']}" for t in terms))

    return Context(text="\n".join(lines), sources="\n".join(sources), terms=terms, file=scope.file)


def guess_file(project: Project, reg: Registry | None, scope: Scope) -> str | None:
    """网页没指明文件时，按选项卡猜一个：讲解看 notebook，执行计划看 plan.md。"""
    if scope.file or reg is None or not scope.step:
        return scope.file
    from ..core.steps import revision_files

    try:
        step = find_step(reg, scope.step)
        rev = pick_revision(step, scope.rev or None)
    except KeyError:
        return None
    files, _ = revision_files(project.root, rev.dir, exclude_revisions=False)
    want = {"guide": ("notebook",), "code": ("notebook", "code"), "plan": ("plan", "plan_user", "approval"),
            "data": (), "board": (), "log": ("execution_record",), "products": ()}.get(scope.tab or "", ())
    for kind in want:
        for f in files:
            if f["kind"] == kind:
                return posixpath.normpath(f["path"])
    return None
