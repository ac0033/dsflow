import type {
  Alert,
  AskEvent,
  AskModelRow,
  AskModels,
  AskRecord,
  AskStatus,
  ApprovalView,
  DecisionResult,
  Board,
  ChecklistReport,
  ModelDetail,
  ModelEntry,
  ModelStatus,
  ModelVersion,
  Knowledge,
  StepChecks,
  Tracker,
  TrackerKind,
  CheckResult,
  ColumnNote,
  CheckSpec,
  DataOverview,
  Distribution,
  FileMeta,
  GuideTerm,
  GuideView,
  Job,
  Lineage,
  Peek,
  Profile,
  StepTables,
  StepStock,
  Run,
  RunDetail,
  StepDetail,
  ProjectDetail,
  ProjectRow,
  TablePage,
} from './types'

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    throw new ApiError(res.ok ? '后端返回的不是 JSON' : `请求失败（${res.status}），后端可能未启动`, res.status)
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail
    throw new ApiError(typeof detail === 'string' ? detail : `请求失败（${res.status}）`, res.status)
  }
  return data as T
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) })
const qs = (params: Record<string, string | number | boolean | undefined | null>) =>
  new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => [k, String(v)]),
  ).toString()

export interface TableQuery {
  path: string
  offset: number
  limit: number
  sort?: string | null
  desc?: boolean
  filters?: { column: string; op: string; value?: string }[]
}

export const api = {
  health: () => request<{ ok: boolean; version: string }>('/health'),
  projects: () => request<ProjectRow[]>('/projects'),
  addProject: (path: string, readonly: boolean) => post<ProjectRow>('/projects', { path, readonly }),
  removeProject: (id: string) => request<{ removed: boolean }>(`/projects/${id}`, { method: 'DELETE' }),
  project: (id: string) => request<ProjectDetail>(`/projects/${id}`),
  step: (id: string, stepId: string) => request<StepDetail>(`/projects/${id}/steps/${encodeURIComponent(stepId)}`),
  file: (id: string, path: string) =>
    request<{ path: string; size: number; suffix: string; content: string }>(`/projects/${id}/file?${qs({ path })}`),
  lineage: (id: string) => request<Lineage>(`/projects/${id}/data/lineage`),
  runs: (id: string, step?: string) => request<Run[]>(`/projects/${id}/runs?${qs({ step })}`),
  run: (id: string, runId: string) => request<RunDetail>(`/projects/${id}/runs/${runId}`),
  runLog: (id: string, runId: string) =>
    request<{ text: string; truncated: boolean; size: number; done: boolean }>(`/projects/${id}/runs/${runId}/log`),
  rerun: (id: string, runId: string) => post<Run>(`/projects/${id}/runs/${runId}/rerun`, {}),

  data: (id: string) => request<DataOverview>(`/projects/${id}/data`),
  meta: (id: string, path: string) => request<FileMeta>(`/projects/${id}/data/meta?${qs({ path })}`),
  prepare: (id: string, path: string) => post<Job>(`/projects/${id}/data/prepare`, { path }),
  table: (id: string, q: TableQuery) =>
    request<TablePage>(
      `/projects/${id}/data/table?${qs({
        path: q.path,
        offset: q.offset,
        limit: q.limit,
        sort: q.sort,
        desc: q.desc,
        filters: q.filters?.length ? JSON.stringify(q.filters) : undefined,
      })}`,
    ),
  /** 讲解旁边的数据视图：只取前几行几列，后端不建缓存。 */
  peek: (id: string, path: string, columns: string[], limit: number, sheet = 0) =>
    request<Peek>(`/projects/${id}/data/peek?${qs({ path, columns: columns.join(',') || null, limit, sheet })}`),
  stepTables: (id: string, stepId: string, rev?: string | null) =>
    request<StepTables>(`/projects/${id}/data/steps/${encodeURIComponent(stepId)}/tables?${qs({ rev })}`),
  /** 数据层的存量账：原存量 → 增减量 → 后存量 */
  stepStock: (id: string, stepId: string, rev?: string | null) =>
    request<StepStock>(`/projects/${id}/data/steps/${encodeURIComponent(stepId)}/stock?${qs({ rev })}`),
  sample: (id: string, path: string, n: number, seed: number) =>
    request<TablePage>(`/projects/${id}/data/sample?${qs({ path, n, seed })}`),
  sql: (id: string, path: string, sql: string) => post<TablePage>(`/projects/${id}/data/sql`, { path, sql }),
  profile: async (id: string, path: string): Promise<Profile | null> => {
    try {
      return await request<Profile>(`/projects/${id}/data/profile?${qs({ path })}`)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null
      throw e
    }
  },
  makeProfile: (id: string, path: string) => post<Job<Profile>>(`/projects/${id}/data/profile`, { path }),
  compare: (id: string, body: { a: string; b: string; key: string[]; segment: string | null }) =>
    post<Job>(`/projects/${id}/data/compare`, body),
  /** 这几列在讲解与 notebook 里的出处：哪一段说过它、哪一格动了它 */
  columnNotes: (id: string, stepId: string, body: { columns: string[]; rev?: string | null }) =>
    post<{ step: string; revision: string; notes: Record<string, ColumnNote[]> }>(
      `/projects/${id}/data/steps/${encodeURIComponent(stepId)}/column-notes`, body),
  distribution: (id: string, a: string, b: string, column: string) =>
    post<Distribution>(`/projects/${id}/data/distribution`, { a, b, column }),
  checks: (id: string, a: string, b: string, checks: CheckSpec[]) =>
    post<CheckResult[]>(`/projects/${id}/data/checks`, { a, b, checks }),
  register: (
    id: string,
    body: { path: string; name: string; stage: string; parents: string[]; produced_by: string | null; description: string },
  ) => post<unknown>(`/projects/${id}/data/datasets`, body),
  job: <T>(jobId: string) => request<Job<T>>(`/jobs/${jobId}`),

  board: (id: string) => request<Board>(`/projects/${id}/board`),
  verifyRaw: (id: string) => post<Alert[]>(`/projects/${id}/board/verify`, {}),
  tracker: (id: string) => request<Tracker>(`/projects/${id}/tracker`),
  createItem: (id: string, kind: TrackerKind, body: Record<string, unknown>) =>
    post<unknown>(`/projects/${id}/tracker/${kind}`, body),
  updateItem: (id: string, kind: TrackerKind, itemId: string, patch: Record<string, unknown>) =>
    request<unknown>(`/projects/${id}/tracker/${kind}/${encodeURIComponent(itemId)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteItem: (id: string, kind: TrackerKind, itemId: string) =>
    request<unknown>(`/projects/${id}/tracker/${kind}/${encodeURIComponent(itemId)}`, { method: 'DELETE' }),
  stepChecks: (id: string, stepId: string) => request<StepChecks>(`/projects/${id}/steps/${encodeURIComponent(stepId)}/checks`),
  guide: (id: string, stepId: string, rev?: string | null) =>
    request<GuideView>(`/projects/${id}/steps/${encodeURIComponent(stepId)}/guide?${qs({ rev })}`),
  knowledge: (id: string) => request<Knowledge>(`/projects/${id}/knowledge`),
  approvals: (id: string, stepId: string, rev?: string | null) =>
    request<ApprovalView>(`/projects/${id}/steps/${encodeURIComponent(stepId)}/approval?${qs({ rev })}`),
  decide: (id: string, stepId: string, body: { kind: 'approval' | 'acceptance'; decision: 'approve' | 'reject'; note: string; rev?: string | null }) =>
    post<DecisionResult>(`/projects/${id}/steps/${encodeURIComponent(stepId)}/approval`, body),
  withdraw: (id: string, stepId: string, body: { note: string; rev?: string | null }) =>
    post<DecisionResult>(`/projects/${id}/steps/${encodeURIComponent(stepId)}/approval/withdraw`, body),

  models: (id: string) => request<{ models: ModelEntry[]; readonly: boolean }>(`/projects/${id}/models`),
  model: (id: string, name: string, version: string) =>
    request<ModelDetail>(`/projects/${id}/models/${encodeURIComponent(name)}/${encodeURIComponent(version)}`),
  setModelStatus: (id: string, name: string, version: string, to: ModelStatus, note: string) =>
    post<ModelVersion>(`/projects/${id}/models/${encodeURIComponent(name)}/${encodeURIComponent(version)}/status`, { to, note }),
  makeChecklist: (id: string, name: string, version: string) =>
    post<ChecklistReport>(`/projects/${id}/models/${encodeURIComponent(name)}/${encodeURIComponent(version)}/checklist`, {}),

  /** 术语表：本步登记的 > 项目术语表 > 平台内置。讲解以外的页面（执行计划、代码）也用它标行话。 */
  terms: (id: string, step?: string | null, rev?: string | null) =>
    request<{ terms: GuideTerm[] }>(`/projects/${id}/terms?${qs({ step, rev })}`),
  askStatus: () => request<AskStatus>('/ask/status'),
  /** 答疑用的模型配置：只能在平台所在的这台电脑上读写，密钥不原样返回 */
  askModels: () => request<AskModels>('/ask/models'),
  addAskModel: (body: { preset: string; api_key?: string; name?: string; model?: string; base_url?: string }) =>
    post<AskModelRow>('/ask/models', body),
  useAskModel: (name: string) => post<AskModelRow>(`/ask/models/${encodeURIComponent(name)}/use`, {}),
  deleteAskModel: (name: string) => request<{ removed: string; active: string | null }>(`/ask/models/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  /** 真的向模型发一句最短的话，看通不通 */
  testAskModel: (name?: string) => post<{ ok: boolean; message: string; model?: string }>(`/ask/models/test?${qs({ name })}`, {}),
  asks: (id: string, step?: string | null, rev?: string | null) =>
    request<{ records: AskRecord[] }>(`/projects/${id}/asks?${qs({ step, rev })}`),
  deleteAsk: (id: string, askId: string, step?: string | null) =>
    request<{ deleted: boolean }>(`/projects/${id}/asks/${askId}?${qs({ step })}`, { method: 'DELETE' }),
  markAsk: (id: string, askId: string, mark: boolean, step?: string | null) =>
    request<AskRecord>(`/projects/${id}/asks/${askId}`, { method: 'PATCH', body: JSON.stringify({ mark, step }) }),
  saveTerm: (id: string, askId: string, body: { term: string; meaning: string; step?: string | null; source?: string }) =>
    post<{ term: string; path: string }>(`/projects/${id}/asks/${askId}/term`, body),
}

export interface AskBody {
  question: string
  step?: string | null
  rev?: string | null
  tab?: string | null
  file?: string | null
  quote?: string
  /** 先在页面上标好、攒着一起问的几处 */
  notes?: { quote: string; note: string }[]
  mark?: boolean
  tools?: boolean
  history?: { question: string; answer: string }[]
}

/**
 * 提问：后端按 SSE 一条条推事件（tool / result / text / done / error），这里边收边回调，界面就有打字效果。
 * 用 fetch 而不是 EventSource，因为要 POST 一整个上下文过去。
 */
/** SSE 里一条事件和下一条之间隔一个空行 */
const SEP = '\n\n'

export async function askStream(id: string, body: AskBody, onEvent: (event: AskEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`/api/projects/${id}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) throw new ApiError(`提问失败（${res.status}），后端可能未启动`, res.status)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    for (let at = buffer.indexOf(SEP); at >= 0; at = buffer.indexOf(SEP)) {
      const chunk = buffer.slice(0, at)
      buffer = buffer.slice(at + SEP.length)
      const line = chunk.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      try {
        onEvent(JSON.parse(line.slice(6)) as AskEvent)
      } catch {
        /* 半条事件就丢掉，不让整轮问答崩掉 */
      }
    }
  }
}
