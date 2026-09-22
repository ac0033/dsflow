"""DSFlow 的核心数据契约。

注册表（lifecycle/steps.json）的字段定义；未知字段原样保留（extra="allow"），
平台只读取、不改写。步骤说明卡、运行记录、数据版本等为 DSFlow 扩展。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

StepStatus = Literal[
    "pending", "pending_approval", "in_progress", "awaiting_acceptance", "partial", "done", "stopped"
]

STATUS_LABEL: dict[str, str] = {
    "pending": "未开始",
    "pending_approval": "待审批",
    "in_progress": "进行中",
    "awaiting_acceptance": "待验收",
    "partial": "部分完成",
    "done": "已完成",
    "stopped": "已停止",
}


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# ---------- 注册表 ----------


class Stage(_Open):
    id: int
    name: str
    dir: str
    color: str = "#64748b"


class Revision(_Open):
    id: str
    status: StepStatus
    dir: str
    summary: str = ""
    acceptance_report: str | None = None


class Dependency(_Open):
    from_: str = Field(alias="from")
    to: str
    label: str = ""


class BackEdge(Dependency):
    loop: bool = False


class RevisionLoop(_Open):
    step: str
    from_revision: str
    to_revision: str
    label: str = ""


class Group(_Open):
    name: str
    summary: str = ""


class Step(_Open):
    id: str
    stage: int
    order: int
    title: str
    dir: str
    status: StepStatus
    op: str = ""
    finding: str = ""
    decision: str = ""
    execution_notebooks: list[str] | None = None
    # DSFlow 扩展：用脚本执行（运行记录在平台里）时登记脚本，可代替 notebook
    execution_scripts: list[str] | None = None
    current_revision: str | None = None
    revisions: list[Revision] = []
    acceptance_report: str | None = None
    group: str | None = None
    # DSFlow 扩展：流程图节点上的一句话结论与关键产物
    headline: str | None = None
    key_artifacts: list[str] = []


class Registry(_Open):
    title: str
    stages: list[Stage]
    steps: list[Step]
    # 缺失即校验失败：禁止按编号推导依赖
    dependencies: list[Dependency] | None = None
    back_edges: list[BackEdge] = []
    revision_loops: list[RevisionLoop] = []
    groups: dict[str, Group] = {}
    notes: str = ""


# ---------- 项目配置（dsflow.yaml） ----------


class DatasetEntry(_Open):
    name: str
    path: str
    stage: str = "raw"
    description: str = ""


class ProjectConfig(_Open):
    name: str
    question: str = ""
    registry: str = "lifecycle/steps.json"
    vocabulary: str = "vocabulary.json"
    datasets: list[DatasetEntry] = []
    metric_goals: dict[str, Literal["min", "max"]] = Field(
        {}, description="指标方向：min 越小越好 / max 越大越好；停止规则据此判断提升"
    )
    guide_lint: dict[str, dict[str, int]] = Field(
        {}, description="讲解体检的字数阈值覆盖：limits（开头六段上限）、cell_limits（每格上限）、min_len（下限）"
    )


# ---------- 步骤说明卡（step_card.yaml） ----------


class CoreNumber(_Open):
    label: str
    before: float | int | str | None = None
    change: float | int | str | None = None
    after: float | int | str | None = None
    unit: str = ""
    scope: str = Field("", description="口径：记录数还是不同值个数、期间、范围")
    source: str | None = Field(
        None,
        description="可重算的出处，用来核对「处理后」的数字：<产物路径>#<取值方式>。路径相对本轮目录；"
                    "取值方式：rows | sum:列 | count:列 | distinct:列 | mean:列 | min:列 | max:列 | sql:查询（表名 data）| /JSON/指针",
    )


class ArtifactRef(_Open):
    path: str
    purpose: str = Field(description="这个产物是干什么用的")
    kind: Literal["table", "figure", "model", "report", "log", "other"] = "other"


class Example(_Open):
    title: str
    input: str
    rule: str
    output: str
    artifact: str | None = None
    real: bool = Field(True, description="False 表示虚构示意，界面必须标明")


class StepCard(_Open):
    step: str
    revision: str | None = None
    headline: str = Field(description="首屏一句话：完成了吗、验收是否通过、能否继续")
    can_continue: bool | None = None
    core_numbers: list[CoreNumber] = []
    operation: str = Field("", description="用直白的话说主要操作")
    exceptions: list[str] = Field([], description="只列影响判断的例外")
    artifacts: list[ArtifactRef] = []
    why: str = ""
    invariants: list[str] = []
    concentration: str = Field("", description="变化集中在哪里")
    evidence: list[ArtifactRef] = []
    can_say: list[str] = []
    cannot_say: list[str] = []
    next: str = ""
    examples: list[Example] = []


# ---------- notebook 导读（guide.yaml） ----------


class GuideBrief(_Open):
    """开头六段：背景、目的、结论、操作、结果、下一步建议。写给只看这一屏就要判断能不能往下走的人。"""

    background: str = Field("", description="背景：为什么要有这一步，和上一步是什么关系，一句")
    question: str = Field(description="目的：这一步要回答什么，用业务的话说，一句")
    answer: str = Field(description="结论：回答上面那个问题，一句。最多带一个数字")
    can_continue: bool | None = Field(None, description="能不能往下走")
    did: str = Field("", description="操作：做了什么，一句白话，不写数字")
    result: str = Field("", description="结果：这些操作做完实现了什么、留下了哪些核心产出（写产物名与它现在能干什么，和目的、操作对得上）")
    next: str = Field("", description="下一步建议：接下来该做什么、可以不做什么")


class GuideMark(_Open):
    """数据视图里要点出来的地方：哪几列、哪几行（行按 0 起算，指这一屏里的第几行）。"""

    columns: list[str] = []
    rows: list[int] = []
    note: str = Field("", description="点出来之后要说的一句话")


class GuideFrame(_Open):
    """数据视图的一屏：一份数据文件的前几行、只取几列。平台按需读，不整表转换。"""

    label: str = Field(description="这一屏是什么，如 处理前 / 处理后")
    file: str = Field(description="数据文件路径，相对项目根目录；xlsx / csv / parquet")
    columns: list[str] = Field([], description="只看这几列；不写就取前几列")
    limit: int = Field(5, ge=1, le=20, description="取前几行")
    sheet: int = Field(0, description="xlsx 的第几个工作表，从 0 起")
    mark: GuideMark | None = None
    caption: str = Field("", description="这一屏底下的一句说明")


class GuideData(_Open):
    """挂在某一格旁边的数据视图：用这份数据的几行几列，让人对照着看这格代码做了什么。

    一屏就是静态对照；两屏（处理前 / 处理后）平台会给切换按钮，切换时带变化动画。
    """

    title: str = Field("", description="这个数据视图在给人看什么")
    frames: list[GuideFrame] = Field(description="1～2 屏")
    note: str = Field("", description="一句提醒，如“只读了表头，没把整表读进内存”")


class GuideLine(_Open):
    line: int = Field(ge=1, description="单元格内第几行（从 1 数）")
    note: str
    cell: int | None = Field(None, description="一条讲解引用多个单元格时，指明是哪个")
    mark: GuideMark | None = Field(None, description="点这一行时，数据视图里跟着亮起来的列或行")


class GuideCell(_Open):
    """一个（或几个）单元格的旁注：在做什么、为什么这样做、输出怎么读。"""

    cell: int | list[int] = Field(description="notebook 里第几个单元格（从 1 数，说明单元格也算）")
    notebook: str | None = Field(None, description="不用本部分默认 notebook 时写")
    title: str = ""
    what: str = Field("", description="在做什么")
    why: str = Field("", description="为什么这样做：防的是什么风险、少了会怎样")
    read: str = Field("", description="输出怎么读：指着具体的输出数字说它意味着什么")
    lines: list[GuideLine] = Field([], description="只给不容易看懂的行加注，一格最多三条")
    data: GuideData | None = Field(None, description="核心的格子才配数据视图，让人对照源数据看")


class GuidePart(_Open):
    question: str = Field(description="读者要弄明白的一个问题")
    answer: str = ""
    meaning: str = Field("", description="业务含义：这一段的结论对业务意味着什么")
    notebook: str | None = None
    cells: list[GuideCell] = []


class GuideTerm(_Open):
    term: str
    plain: str = Field(description="白话解释（本步特有的说法；通用词平台内置了术语表）")
    aliases: list[str] = []


class Guide(_Open):
    """notebook 导读：写给懂业务、懂技术原理、能读代码，但没做过数据科学的负责人。

    只讲 notebook 里真实的单元格和输出，不复述用户报告；数字照输出原样写，平台会逐个回到输出里核对。
    """

    step: str
    revision: str | None = None
    notebook: str | None = Field(None, description="主 notebook，相对本轮目录；不写时取本轮第一个 notebook")
    brief: GuideBrief
    parts: list[GuidePart] = []
    terms: list[GuideTerm] = []
    cannot_say: list[str] = Field([], description="别误读：这一步没有证明什么")


# ---------- 运行与数据版本 ----------


class DatasetRef(_Open):
    name: str
    version: str
    path: str
    sha256: str | None = None
    rows: int | None = None
    columns: int | None = None


class Run(_Open):
    """一次运行：用了什么数据、什么代码、什么参数、为了验证什么假设、结论是什么。"""

    run_id: str
    step: str
    revision: str | None = None
    command: str = ""
    argv: list[str] = []
    cwd: str | None = None
    source: Literal["cli", "sdk", "ui", "tool"] = "sdk"
    rerun_of: str | None = None
    pid: int | None = None
    started_at: str
    ended_at: str | None = None
    duration_s: float | None = None
    status: Literal["running", "succeeded", "failed"] = "running"
    exit_code: int | None = None
    error: str | None = None
    git_commit: str | None = None
    git_dirty: bool | None = None
    env: dict[str, str] = {}
    params: dict[str, Any] = {}
    metrics: dict[str, float | None] = {}
    fold_metrics: dict[str, dict[str, float | None]] = Field({}, description="逐折指标：{折: {指标: 值}}")
    hypothesis: str = ""
    conclusion: str = ""
    validity: Literal["有效", "无效", "无结论"] | None = None
    inputs: list[DatasetRef] = []
    outputs: list[DatasetRef] = []
    artifacts: list[ArtifactRef] = []
    figures: list[dict[str, str]] = []
    deltas: list[dict[str, Any]] = Field([], description="输出数据与每个输入的结构/行数/逐列变化摘要")
    models: list[dict[str, str]] = Field([], description="本次运行登记的模型版本：{name, version, path}")


class DatasetVersion(_Open):
    name: str
    version: str = Field(description="内容 SHA256 前 12 位")
    sha256: str
    path: str
    format: Literal["csv", "xlsx", "parquet", "other"]
    size_bytes: int
    rows: int | None = None
    columns: int | None = None
    stage: str = "raw"
    produced_by: str | None = None
    parents: list[str] = []
    replaces: list[str] = Field([], description="这一版登记后，哪些数据集就不再是有用的最终文件了（被它替代，退出存量）")
    registered_at: str


class InvariantCheck(_Open):
    """步骤声明的"必须不变"，由平台在处理前后两份数据上自动核对。"""

    type: Literal[
        "row_count_equal", "row_count_max_change", "sum_equal", "columns_unchanged", "no_new_nulls",
        "keys_preserved",
    ]
    key: list[str] = []
    columns: list[str] = []
    column: str | None = None
    tolerance: float = 0.0
    description: str = ""


# ---------- 模型与交付 ----------

ModelStatus = Literal["candidate", "accepted", "delivered"]
MODEL_STATUS_LABEL: dict[str, str] = {"candidate": "候选", "accepted": "已验收", "delivered": "已交付"}


class StatusChange(_Open):
    status: ModelStatus
    at: str
    note: str = ""


class ModelVersion(_Open):
    """一个模型版本：模型文件按内容哈希区分；数据版本、代码版本、指标都从产出它的运行记录追溯。"""

    name: str
    version: str = Field(description="模型文件 SHA256 前 12 位")
    sha256: str
    path: str
    size_bytes: int
    mtime_ns: int | None = Field(None, description="登记时的修改时间，用来不算哈希地快速发现文件被动过")
    run_id: str | None = Field(None, description="产出这个模型的运行")
    step: str | None = None
    description: str = ""
    status: ModelStatus = "candidate"
    history: list[StatusChange] = []
    registered_at: str


class ChecklistMetric(_Open):
    name: str
    value: float | None = None
    baseline: str = Field("", description="对照：基线是多少、差多少")
    scope: str = Field("", description="口径：在哪些数据上、按什么粒度算的")


class Applicability(_Open):
    scope: list[str] = Field([], description="适用于什么：对象、期间、粒度")
    not_for: list[str] = Field([], description="不适用于什么")
    data_period: str = Field("", description="训练数据覆盖的期间")
    known_weaknesses: list[str] = []


class MonitoringItem(_Open):
    metric: str
    threshold: str
    frequency: str
    action: str = Field(description="超过阈值后做什么")


class DeliveryChecklist(_Open):
    """交付清单（delivery/<模型名>/checklist.yaml）。model、version、reproduce、data、metrics 的数值由平台生成；
    其余由执行 agent 或负责人填写，平台刷新时保留。"""

    model: str
    version: str
    summary: str = Field("", description="一句话：交付什么、用来回答什么业务问题")
    reproduce: list[str] = Field([], description="复现入口：还原代码、依赖，核对数据与模型文件，重跑训练")
    usage: list[str] = Field([], description="使用入口：怎样用这个模型得到结果")
    data: list[DatasetRef] = Field([], description="训练数据版本")
    metrics: list[ChecklistMetric] = []
    applicability: Applicability = Field(default_factory=Applicability)
    monitoring: list[MonitoringItem] = []
    deployment: str = Field("待定", description="部署方式；未定时写「待定」")
    artifacts: list[ArtifactRef] = []
    open_items: list[str] = Field([], description="交付时仍未解决、使用方需要知道的问题")


# ---------- 问题、决策、术语 ----------


class Issue(_Open):
    id: str
    title: str
    step: str | None = None
    revision: str | None = None
    run_id: str | None = None
    severity: Literal["低", "中", "高"] = "中"
    blocking: bool = False
    status: Literal["open", "resolved"] = "open"
    created_at: str
    resolved_at: str | None = None
    note: str = ""


class Decision(_Open):
    """决策日志：背景、决策、依据、放弃的方案、影响范围。"""

    id: str
    date: str
    title: str
    context: str = ""
    decision: str
    basis: list[str] = []
    rejected: list[str] = []
    impact: str = ""
    step: str | None = None
    created_at: str = ""


class PendingDecision(_Open):
    """待决事项：需要用户裁定的业务口径或方向，是否阻塞后续执行。"""

    id: str
    question: str
    recommendation: str = ""
    basis: str = ""
    alternatives: str = ""
    impact: str = ""
    blocking: bool = False
    status: Literal["unresolved", "resolved"] = "unresolved"
    resolved_answer: str = ""
    step: str | None = None
    created_at: str = ""
    resolved_at: str | None = None


class VocabTerm(_Open):
    term: str
    meaning: str
    source: str = Field(description="出处：数据表字段、表名或既有对话")
    avoid: list[str] = Field([], description="不要使用的同义说法")


class Vocabulary(_Open):
    terms: list[VocabTerm] = []


CONTRACTS: dict[str, type[BaseModel]] = {
    "registry": Registry,
    "project_config": ProjectConfig,
    "step_card": StepCard,
    "guide": Guide,
    "run": Run,
    "dataset_version": DatasetVersion,
    "invariant_check": InvariantCheck,
    "model_version": ModelVersion,
    "delivery_checklist": DeliveryChecklist,
    "issue": Issue,
    "decision": Decision,
    "pending_decision": PendingDecision,
    "vocabulary": Vocabulary,
}
