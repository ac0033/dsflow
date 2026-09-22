export type StepStatus =
  | 'pending'
  | 'pending_approval'
  | 'in_progress'
  | 'awaiting_acceptance'
  | 'partial'
  | 'done'
  | 'stopped'

export interface ProjectRow {
  id: string
  name: string
  root: string
  readonly: boolean
  added_at: string
  scanned_at: string | null
  step_count: number | null
  error_count: number | null
  status_counts: Partial<Record<StepStatus, number>>
}

export interface Stage {
  id: number
  name: string
  dir: string
  color: string
}

export interface Revision {
  id: string
  status: StepStatus
  dir: string
  summary: string
  acceptance_report?: string | null
}

export interface StepNode {
  id: string
  stage: number
  order: number
  title: string
  dir: string
  status: StepStatus
  status_label: string
  op: string
  finding: string
  decision: string
  current_revision?: string | null
  revisions: Revision[]
  headline?: string | null
  key_artifacts: string[]
  report_path: string
  report_available: boolean
  revision_count: number
  card?: CardSummary | null
  issue_count: number
  /** 当前轮次讲解的开头（背景 / 目的 / 结论 / 能否继续 / 下一步）；没有导读时为 null */
  brief?: StepBriefLine | null
}

/** 讲解开头，讲给人听的话；流程图节点、阶段概况、看板都用它，不用注册表原话 */
export interface StepBriefLine {
  revision: string
  background: string
  question: string
  answer: string
  can_continue: boolean | null
  did: string
  next: string
  parts: number
}

export interface Edge {
  from: string
  to: string
  type: 'dependency' | 'back' | 'revision_loop'
  label: string
  from_revision?: string
  to_revision?: string
}

export interface Graph {
  title: string
  stages: Stage[]
  nodes: StepNode[]
  edges: Edge[]
  notes: string
  path: PathEntry[]
}

// ---------- 步骤工作区 ----------

export type CardValue = number | string | null | undefined

export interface CoreNumber {
  label: string
  before?: CardValue
  change?: CardValue
  after?: CardValue
  unit: string
  scope: string
  source?: string | null
}

export interface ArtifactRef {
  path: string
  purpose: string
  kind: string
}

export interface CardExample {
  title: string
  input: string
  rule: string
  output: string
  artifact?: string | null
  real: boolean
}

export interface StepCard {
  step: string
  revision?: string | null
  headline: string
  can_continue: boolean | null
  core_numbers: CoreNumber[]
  operation: string
  exceptions: string[]
  artifacts: ArtifactRef[]
  why: string
  invariants: string[]
  concentration: string
  evidence: ArtifactRef[]
  can_say: string[]
  cannot_say: string[]
  next: string
  examples: CardExample[]
}

// ---------- notebook 导读（讲解） ----------

/** 开头五段：背景 / 目的 / 结论 / 操作 / 下一步建议。 */
export interface GuideBrief {
  background: string
  question: string
  answer: string
  can_continue: boolean | null
  did: string
  /** 结果：操作做完实现了什么、留下哪些核心产出 */
  result: string
  next: string
}

export interface GuideMark {
  columns: string[]
  rows: number[]
  note: string
}

export interface GuideFrame {
  label: string
  file: string
  columns: string[]
  limit: number
  sheet: number
  mark?: GuideMark | null
  caption: string
}

export interface GuideData {
  title: string
  frames: GuideFrame[]
  note: string
}

export interface GuideLine {
  line: number
  note: string
  cell?: number | null
  mark?: GuideMark | null
}

export interface GuideCell {
  cell: number | number[]
  notebook?: string | null
  title: string
  what: string
  why: string
  read: string
  lines: GuideLine[]
  data?: GuideData | null
}

/** 以数据表为主线看一个步骤：进来什么样、出去什么样、变了哪些列。 */
export interface ColumnDiff {
  known: boolean
  added: string[]
  removed: string[]
  kept: number
}

/** 讲解里配了数据视图的地方：第几段、哪一格、给人看什么 */
export interface GuideRef {
  part: number
  question: string
  cell_title: string
  title: string
  label: string
  caption: string
  columns: string[]
}

/** 存量账里的角色：存量（执行前 / 后都有的）、新增、更新（换了新版本）、退出（被替代）；其余是只读没改和讲解引用 */
export type TableRole = '输入' | '产出' | '核对' | '读取' | '讲解引用' | '本轮产物' | '存量' | '新增' | '更新' | '退出' | '中间产物'

/** 一列的出处：讲解里哪一段说过它，或 notebook 哪一格动了它 */
export interface ColumnNote {
  source: '讲解' | '代码' | '说明'
  part: number | null
  cell: number | null
  where: string
  title: string
  quote: string
}

/** 新增的表是从哪张上游表来的：名字与规模，多张就是合并 */
export interface TableSource {
  name: string
  path: string | null
  version?: string
  rows: number | null
  columns: number | null
  missing: boolean
  ready: boolean
}

export interface StepTable {
  name: string
  path: string
  role: TableRole
  /** 名字下面那行小字：这份数据的简要介绍 */
  note: string
  /** 还没有写介绍，note 里是平台的提示句 */
  note_missing?: boolean
  guide_refs: GuideRef[]
  produced_by?: string | null
  replaces?: string[]
  /** 新增：上游的几张表（多于一张就是合并） */
  sources?: TableSource[]
  /** 更新：换掉的旧版本 */
  previous_version?: string | null
  previous_path?: string | null
  previous_rows?: number | null
  previous_columns?: number | null
  /** 退出：被哪张表替代，那张表有多大 */
  retired_by?: string
  retired_by_path?: string | null
  retired_by_rows?: number | null
  retired_by_columns?: number | null
  /** 新增：和哪张表比的列变化，以及那张表的路径（对比页成对用） */
  diff_base_path?: string | null
  /** 说明卡里声明了用途的产物（没登记为数据集） */
  declared?: boolean
  ready: boolean
  missing: boolean
  rows: number | null
  columns: number | null
  size: number | null
  format?: string
  stage?: string
  stage_label?: string
  version?: string
  parents?: string[]
  diff?: ColumnDiff | null
  diff_base?: string | null
}

export interface StepOther {
  path: string
  rel: string
  size: number
  kind: string
  kind_label: string
}

export interface StepTables {
  step: string
  revision: string
  revision_dir: string
  changes_data: boolean
  tables: StepTable[]
  others: StepOther[]
  chain: ChainItem[]
}

/** 这一步产出的非表格产物：说明卡声明的、本轮的用户报告与验收报告 */
export interface StockOther {
  path: string
  rel: string
  kind: string
  kind_label: string
  purpose: string
  exists: boolean
}

/** 数据层的存量账：原存量 → 增减量 → 后存量。产物只算有用的最终文件。 */
export interface StepStock {
  step: string
  revision: string
  revision_dir: string
  changes_data: boolean
  /** 中间产物：本轮目录里留下的、没进存量账的数据文件（报告、说明这类不算） */
  middles: StepTable[]
  before: StepTable[]
  delta: {
    added: StepTable[]
    updated: StepTable[]
    retired: StepTable[]
    checked: StepTable[]
    others: StockOther[]
  }
  after: StepTable[]
}

/** 数据视图的一屏：前几行、只取几列，后端不建缓存直接读。 */
export interface Peek {
  path: string
  format: string
  columns: string[]
  rows: (string | number | boolean | null)[][]
  limit: number
  total_columns: number | null
  size: number
}

export interface GuidePart {
  question: string
  answer: string
  meaning: string
  notebook?: string | null
  cells: GuideCell[]
}

export interface GuideTerm {
  term: string
  plain: string
  aliases: string[]
  source?: string
}

export interface Guide {
  step: string
  revision?: string | null
  notebook?: string | null
  brief: GuideBrief
  parts: GuidePart[]
  terms: GuideTerm[]
  cannot_say: string[]
}

export interface GuideChecks {
  errors: string[]
  checked: number
  found: number
  missing: { where: string; part: number | null; cell: number | null; number: string }[]
}

export interface GuideView {
  step: string
  revision: string
  notebooks: string[]
  notebook: string | null
  revision_dir: string
  guide: Guide | null
  error: string | null
  source: string
  stored_in: string
  target: string
  readonly: boolean
  checks: GuideChecks | null
  terms: GuideTerm[]
}

export interface CardSummary {
  headline: string
  can_continue: boolean | null
  numbers: CoreNumber[]
  artifacts: string[]
}

export interface RunDatasetRef {
  name: string
  version: string
  path: string
  sha256?: string | null
  rows?: number | null
  columns?: number | null
}

export interface RunDelta {
  input?: string
  input_path?: string
  output: string
  output_path?: string
  rows_a?: number
  rows_b?: number
  row_delta?: number
  columns_a?: number
  columns_b?: number
  added?: string[]
  removed?: string[]
  changed_columns?: number
  flagged?: string[]
  error?: string
}

export type RunStatus = 'running' | 'succeeded' | 'failed'
export type Validity = '有效' | '无效' | '无结论'

export interface Run {
  run_id: string
  step: string
  revision?: string | null
  command: string
  argv: string[]
  cwd?: string | null
  source: 'cli' | 'sdk' | 'ui'
  rerun_of?: string | null
  started_at: string
  ended_at?: string | null
  duration_s?: number | null
  status: RunStatus
  exit_code?: number | null
  error?: string | null
  git_commit?: string | null
  git_dirty?: boolean | null
  env: Record<string, string>
  params: Record<string, unknown>
  metrics: Record<string, number | null>
  fold_metrics: Record<string, Record<string, number | null>>
  hypothesis: string
  conclusion: string
  validity?: Validity | null
  inputs: RunDatasetRef[]
  outputs: RunDatasetRef[]
  artifacts: { path: string; purpose: string; kind: string; sha256?: string }[]
  figures: { name: string; file: string }[]
  deltas: RunDelta[]
  models?: { name: string; version: string; path: string }[]
}

export interface RunDetail extends Run {
  reproduce: { commands: string[]; warnings: string[] }
  readonly: boolean
  log_size: number
}

export interface PathEntry {
  kind: 'revision' | 'run'
  run_id?: string
  validity?: Validity | null
  step: string
  title: string
  stage: number
  order: number
  revision: string
  status: StepStatus
  status_label: string
  date: string | null
  date_source: string | null
  summary: string
}

export interface FileEntry {
  path: string
  rel: string
  size: number
  kind: string
}

export interface RevisionDetail extends Revision {
  status_label: string
  date: string | null
  date_source: string | null
  files: FileEntry[]
  truncated: boolean
  card: StepCard | null
  card_error: string | null
  acceptance_reports: string[]
  is_current: boolean
}

export interface StepInfo {
  id: string
  stage: number
  order: number
  title: string
  dir: string
  status: StepStatus
  status_label: string
  op: string
  finding: string
  decision: string
  current_revision?: string | null
  acceptance_report?: string | null
}

export interface ApprovalEntry {
  time: string
  /** withdraw = 这条是「撤回」，把上一条作废了 */
  decision: 'approve' | 'reject' | 'withdraw'
  decision_label: string
  kind: 'approval' | 'acceptance'
  kind_label: string
  source: string
  note: string
  from: string | null
  to: string | null
}

export interface ApprovalView {
  step: string
  revision: string
  status: StepStatus
  readonly: boolean
  pending: 'approval' | 'acceptance' | null
  path: string | null
  entries: ApprovalEntry[]
  /** 最后一条审批还能不能撤回（只能撤最后一条，且状态没再动过） */
  can_withdraw: boolean
  /** 不能撤时的原因，原样显示给用户 */
  withdraw_blocked: string
}

export interface DecisionResult {
  step: string
  revision: string
  kind: string
  decision: string
  from: string
  to: string
  record: string
  entry: ApprovalEntry
  /** 撤回时：被撤掉的那一条 */
  withdrew?: ApprovalEntry
  warnings: string[]
}

export interface StepDetail {
  step: StepInfo
  stage: Stage | null
  revisions: RevisionDetail[]
  dependencies_in: { step: string; label: string }[]
  dependencies_out: { step: string; label: string }[]
  back_edges: { from: string; to: string; label: string }[]
  revision_loops: { step: string; from_revision: string; to_revision: string; label: string }[]
  issues: ValidationIssue[]
}

export interface LineageNode {
  id: string
  type: 'dataset' | 'step'
  name?: string
  stage_label?: string
  version?: string
  rows?: number | null
  columns?: number | null
  path?: string
  produced_by?: string | null
  missing?: boolean
  step?: string
}

export interface Lineage {
  nodes: LineageNode[]
  edges: { from: string; to: string }[]
}

export interface ValidationIssue {
  code: string
  message: string
  step: string | null
  severity: 'error' | 'warning'
}

// ---------- 数据视图 ----------

export type ColumnKind = 'numeric' | 'temporal' | 'boolean' | 'text' | 'other'
export type Cell = string | number | boolean | null

export interface DataColumn {
  name: string
  type: string
  kind: ColumnKind
}

export interface TablePage {
  columns: DataColumn[]
  rows: Cell[][]
  offset: number
  total: number
  truncated?: boolean
  seed?: number
}

export interface DataFile {
  path: string
  format: 'csv' | 'xlsx' | 'parquet'
  size: number
  modified: string
  registered: boolean
  ready: boolean
  /** 归哪个阶段、哪个步骤：放在步骤目录下的，或登记时写明由这一步产出的 */
  stage?: number | null
  stage_name?: string
  step?: string | null
  /** 登记过的数据集名与它的数据阶段（原始 / 处理后 / 特征 …） */
  dataset?: string | null
  data_stage?: string
}

export interface DatasetVersion {
  name: string
  version: string
  sha256: string
  path: string
  format: string
  size_bytes: number
  rows?: number | null
  columns?: number | null
  stage: string
  produced_by?: string | null
  parents: string[]
  registered_at: string
  missing?: boolean
}

export interface Dataset {
  name: string
  description?: string
  versions: DatasetVersion[]
}

export interface UsedBy {
  step: string
  role: string
}

export interface ChainItem {
  name: string
  description: string
  stage: string
  stage_label: string
  version: string
  path: string
  rows: number | null
  columns: number | null
  produced_by: string | null
  parents: string[]
  replaces?: string[]
  version_count: number
  registered_at: string
  used_by: UsedBy[]
  format?: string
  size_bytes?: number
}

export interface DataOverview {
  readonly: boolean
  files: DataFile[]
  datasets: Dataset[]
  declared: { name: string; path: string; stage: string; description: string }[]
  chain: ChainItem[]
  stages: { id: string; label: string }[]
}

export interface Job<T = unknown> {
  id: string
  kind: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  progress: number | null
  message: string
  result: T | null
  error: string | null
}

export interface FileMeta {
  path: string
  ready: boolean
  conversion: Record<string, unknown> | null
  columns?: DataColumn[]
  rows?: number
  has_profile?: boolean
}

export interface ColumnProfile {
  name: string
  type: string
  kind: ColumnKind
  non_null: number
  null_count: number
  null_rate: number
  distinct_approx: number | null
  min: Cell
  max: Cell
  mean?: number | null
  std?: number | null
  q25?: number | null
  q50?: number | null
  q75?: number | null
  negative?: number
  zero?: number
  blank?: number
  histogram?: { edges: number[]; counts: number[]; under?: number; over?: number }
  p01?: number | null
  p99?: number | null
  periods?: { label: string; count: number }[]
  top?: { value: Cell; count: number }[]
  top_skipped?: string
}

export interface Profile {
  rows: number
  column_count: number
  columns: ColumnProfile[]
  generated_at: string
  seconds: number
}

export interface CompareColumn {
  name: string
  kind: ColumnKind
  null_a: number
  null_b: number
  null_rate_a: number
  null_rate_b: number
  distinct_a: number | null
  distinct_b: number | null
  mean_a?: number | null
  mean_b?: number | null
  q50_a?: number | null
  q50_b?: number | null
  min_a?: number | null
  min_b?: number | null
  max_a?: number | null
  max_b?: number | null
  flags: string[]
}

export interface SegmentRow {
  value: string
  a: number
  b: number
  delta: number
  pct: number | null
  share_a: number | null
  share_of_change: number
}

export interface SegmentImpact {
  column: string
  groups: number
  total_a: number
  total_b: number
  delta: number
  removed: number
  added: number
  rows: SegmentRow[]
  other_groups: number
  concentrated: string[]
}

export interface KeyDiff {
  keys: string[]
  null_keys_a: number
  null_keys_b: number
  duplicates_a: number
  duplicates_b: number
  only_a: number
  only_b: number
  matched: number
  sample_only_a: Record<string, Cell>[]
  sample_only_b: Record<string, Cell>[]
  changed_rows?: number
  changed_by_column?: Record<string, number>
  sample_changed?: { key: Record<string, Cell>; changes: { column: string; a: Cell; b: Cell }[] }[]
  changed_skipped?: string
}

export interface CompareResult {
  a: string
  b: string
  rows: { a: number; b: number; delta: number; pct: number | null }
  column_count: { a: number; b: number }
  schema: { added: string[]; removed: string[]; type_changed: { name: string; a: string; b: string }[] }
  columns: CompareColumn[]
  changed_columns: number
  segment?: SegmentImpact
  key?: KeyDiff
}

export interface Distribution {
  kind: 'numeric' | 'temporal' | 'categorical'
  edges?: number[]
  labels?: string[]
  a: number[]
  b: number[]
  under?: number[]
  over?: number[]
}

export type CheckType =
  | 'row_count_equal'
  | 'row_count_max_change'
  | 'sum_equal'
  | 'columns_unchanged'
  | 'no_new_nulls'
  | 'keys_preserved'

export interface CheckSpec {
  type: CheckType
  key: string[]
  columns: string[]
  column: string | null
  tolerance: number
}

export interface CheckResult {
  type: CheckType
  description: string
  passed: boolean
  detail: string
}

export interface ProjectDetail {
  project: ProjectRow & { question: string }
  graph: Graph | null
  issues: ValidationIssue[]
}

// ---------- 进度与核对 ----------

export type AlertLevel = 'critical' | 'serious' | 'warning' | 'info'

export interface Alert {
  level: AlertLevel
  code: string
  message: string
  step: string | null
  link: string | null
}

export interface StepBrief {
  step: string
  title: string
  status: StepStatus
  status_label: string
  revision: string
  summary: string
}

export interface Issue {
  id: string
  title: string
  step?: string | null
  revision?: string | null
  run_id?: string | null
  severity: '低' | '中' | '高'
  blocking: boolean
  status: 'open' | 'resolved'
  created_at: string
  resolved_at?: string | null
  note: string
}

export interface Decision {
  id: string
  date: string
  title: string
  context: string
  decision: string
  basis: string[]
  rejected: string[]
  impact: string
  step?: string | null
  created_at: string
}

export interface PendingItem {
  id: string
  question: string
  recommendation: string
  basis: string
  alternatives: string
  impact: string
  blocking: boolean
  status: 'unresolved' | 'resolved'
  resolved_answer?: string
  step?: string | null
  created_at?: string
  resolved_at?: string | null
  /** 来自项目文件（decisions_required.json）时才有 */
  revision?: string
  source?: string
}

export type TrackerKind = 'issues' | 'decisions' | 'pending'

export interface Tracker {
  issues: Issue[]
  decisions: Decision[]
  pending: PendingItem[]
  project_pending: PendingItem[]
  readonly: boolean
}

export interface ActivityEvent {
  time: string
  kind: 'commit' | 'run' | 'revision' | 'issue' | 'decision' | 'pending'
  title: string
  step?: string | null
  revision?: string | null
  ref?: string
  status?: RunStatus
}

export interface Iteration {
  step: string
  title: string
  status: StepStatus
  status_label: string
  revisions: number
  loops: number
  back_edges: number
  runs: number
  succeeded: number
  failed: number
  invalid: number
  last_run: string | null
}

// ---------- 模型与交付 ----------

export type ModelStatus = 'candidate' | 'accepted' | 'delivered'

export interface ModelRun {
  run_id: string
  step: string
  revision?: string | null
  status: RunStatus
  validity?: Validity | null
  hypothesis: string
  conclusion: string
  metrics: Record<string, number | null>
  params: Record<string, unknown>
  inputs: RunDatasetRef[]
  git_commit?: string | null
  git_dirty?: boolean | null
  started_at: string
}

export interface ModelVersion {
  name: string
  version: string
  sha256: string
  path: string
  size_bytes: number
  run_id?: string | null
  step?: string | null
  description: string
  status: ModelStatus
  status_label: string
  history: { status: ModelStatus; at: string; note: string }[]
  registered_at: string
  run: ModelRun | null
}

export interface ModelEntry {
  name: string
  description?: string
  versions: ModelVersion[]
}

export interface Gate {
  code: string
  label: string
  passed: boolean
  detail: string
  blocking: boolean
}

export interface DeliveryChecklist {
  model: string
  version: string
  summary: string
  reproduce: string[]
  usage: string[]
  data: RunDatasetRef[]
  metrics: { name: string; value: number | null; baseline: string; scope: string }[]
  applicability: { scope: string[]; not_for: string[]; data_period: string; known_weaknesses: string[] }
  monitoring: { metric: string; threshold: string; frequency: string; action: string }[]
  deployment: string
  artifacts: ArtifactRef[]
  open_items: string[]
}

export interface ChecklistReport {
  path: string
  exists: boolean
  error: string | null
  notes: string[]
  items: { label: string; passed: boolean; detail: string }[]
  passed: number
  total: number
  complete: boolean
  summary: string
  checklist: DeliveryChecklist | null
}

export interface ModelDetail extends ModelVersion {
  target: ModelStatus
  gates: Gate[]
  checklist: ChecklistReport
  readonly: boolean
}

export interface Board {
  total_steps: number
  model_counts?: Partial<Record<ModelStatus, number>>
  status_counts: Partial<Record<StepStatus, number>>
  notes: string
  stages: { id: number; name: string; color: string; total: number; done: number; active: number }[]
  attention: {
    pending_approval: StepBrief[]
    awaiting_acceptance: StepBrief[]
    unfinished: StepBrief[]
    blocking_decisions: PendingItem[]
    open_issues: Issue[]
  }
  alerts: Alert[]
  iterations: Iteration[]
  activity: ActivityEvent[]
  tracker_counts: { open_issues: number; decisions: number; unresolved_pending: number }
}

export interface NumberCheck {
  label: string
  expected: CardValue
  source?: string | null
  actual?: number
  status: 'match' | 'mismatch' | 'no_source' | 'error'
  detail: string
}

export interface StepChecks {
  step: string
  revision: string
  has_card: boolean
  card_error: string | null
  numbers: { items: NumberCheck[]; checked: number; matched: number; total: number }
  vocabulary: boolean
  terms: { avoid: { found: string; use: string; count: number }[]; unregistered: string[] } | null
}

export interface StopPoint {
  run_id: string
  time: string
  value: number
  best: number
  gain: number | null
  hypothesis: string
}

export interface StopRule {
  step: string
  metric: string
  direction: 'min' | 'max' | null
  points: StopPoint[]
  level: 'stop' | 'continue' | 'insufficient' | 'unknown'
  hint: string
}

export interface Knowledge {
  steps: {
    step: string
    title: string
    status: StepStatus
    status_label: string
    revision: string
    has_card: boolean
    headline: string
    can_say: string[]
    cannot_say: string[]
    next: string
    finding: string
    decision: string
  }[]
  open_questions: PendingItem[]
  exploration: {
    run_id: string
    step: string
    started_at: string
    status: RunStatus
    validity?: Validity | null
    hypothesis: string
    conclusion: string
    error?: string | null
  }[]
  stop_rules: StopRule[]
}

/* ---------- 答疑：选中一句话就能问，问答与标注存在平台目录里 ---------- */

/** 一条问答：问了什么、引的是哪句话、答的是什么、有没有钉在页面上 */
/** 答案里提到的一个去处：数据文件 / 代码文件 / notebook 的某一格 */
export interface AskLink {
  kind: 'data' | 'file' | 'cell'
  label: string
  path: string | null
  step: string | null
  cell: number | null
}

/** 问答里带的一处标注：页面上选中的原文 + 用户写的备注 */
export interface AskNoteRecord {
  quote: string
  note: string
}

export interface AskRecord {
  id: string
  at: number
  question: string
  answer: string
  step: string
  rev: string
  tab: string
  file: string
  quote: string
  /** 一次问多处时，每处的原文与用户自己写的备注 */
  notes: AskNoteRecord[]
  /** 钉住：问过的那几句会一直高亮在页面上，点开就是这条问答 */
  mark: boolean
  model: string
  tools: string[]
  /** 答案里没能在上下文或工具返回里找到出处的数字 */
  unverified: string[]
  /** 答案里提到、项目里确实有的东西：点一下跳到数据或讲解的那一格 */
  links: AskLink[]
  saved_term: string
  error: string
}

/** 答疑能不能用：配没配模型、是哪一个、缺什么 */
export interface AskStatus {
  ready: boolean
  model: string | null
  provider?: string
  model_id?: string
  models: string[]
  hint: string
}

/** 提问过程中后端推来的一条事件 */
export type AskEvent =
  | { type: 'text'; delta: string }
  | { type: 'tool'; name: string; args: Record<string, unknown> }
  | { type: 'result'; name: string; ok: boolean; message: string }
  | { type: 'done'; record: AskRecord }
  | { type: 'error'; message: string }

/** 配好的一个模型（密钥只回打码后的样子） */
export interface AskModelRow {
  name: string
  provider: string
  model: string
  base_url: string | null
  preset: string | null
  key: string
  ready: boolean
  active: boolean
}

/** 可选的一家模型服务：默认模型、去哪里申请密钥、要不要密钥 */
export interface AskPreset {
  preset: string
  label: string
  model: string
  base_url: string | null
  where: string
  needs_key: boolean
  env: string
}

export interface AskModels {
  models: AskModelRow[]
  presets: AskPreset[]
  /** 配置存在本机的哪个文件 */
  path: string
  env_hint: string
}
