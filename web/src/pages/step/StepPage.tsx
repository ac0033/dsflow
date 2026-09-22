import { useMemo } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import { api } from '../../api'
import FileViewer from '../../components/FileViewer'
import StatusBadge, { STATUS_COLOR } from '../../components/StatusBadge'
import TabGroups, { type TabGroup } from '../../components/TabGroups'
import { useTerms } from '../../components/Terms'
import { useAskScope } from '../../components/ask/AskContext'
import { fmtTime } from '../../lib/format'
import type { FileEntry, Graph, RevisionDetail, StepDetail } from '../../types'
import ApprovalBar from './ApprovalBar'
import GuideView from './GuideView'
import StepBoard from './StepBoard'
import { DocTabs } from './StepFiles'
import StepProducts from './StepProducts'
import StepRuns from './StepRuns'
import StepTables from './StepTables'

type Tab = 'guide' | 'board' | 'data' | 'plan' | 'code' | 'log' | 'products'
/** 旧链接里的选项卡名，落到新的三层里 */
const LEGACY: Record<string, Tab> = { explain: 'guide', read: 'guide', card: 'board', report: 'data', acceptance: 'data', runs: 'log', files: 'products', compare: 'data' }

/**
 * 步骤工作区：每一步、每一轮都是同样三层——
 * 业务层（讲解、看板）说做了什么、结论是什么；数据层（数据）说产物从什么变成了什么；执行层（执行计划、代码、执行日志、产物）是怎么做的、做出了什么文件。
 */
export default function StepPage() {
  const { id = '', stepId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const project = useQuery({ queryKey: ['project', id], queryFn: () => api.project(id) })
  const detail = useQuery({ queryKey: ['step', id, stepId], queryFn: () => api.step(id, stepId) })
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    Object.entries(patch).forEach(([k, v]) => (v == null ? next.delete(k) : next.set(k, v)))
    setParams(next)
  }

  const d = detail.data
  return (
    <div className="h-full min-h-0 overflow-auto px-6 py-4">
      {detail.isLoading && <p className="text-sm text-slate-500">读取步骤…</p>}
      {detail.error && <p className="text-sm text-red-600">{(detail.error as Error).message}</p>}
      {d && <Workspace key={stepId} pid={id} d={d} graph={project.data?.graph} root={project.data?.project.root} readonly={project.data?.project.readonly} params={params} set={set} />}
    </div>
  )
}

/** 当前选项卡正在读的那个文件：答疑要靠它知道用户在看什么。 */
function planFile(tab: Tab, plans: FileEntry[], code: FileEntry[], records: FileEntry[]): string | null {
  const first = { plan: plans, code, log: records }[tab as 'plan' | 'code' | 'log']
  return first?.[0]?.path ?? null
}

function pickRev(d: StepDetail, wanted: string | null): RevisionDetail {
  return d.revisions.find((r) => r.id === wanted) ?? d.revisions.find((r) => r.is_current) ?? d.revisions[d.revisions.length - 1]
}

function Workspace({ pid, d, graph, root, readonly, params, set }: {
  pid: string
  d: StepDetail
  graph?: Graph | null
  root?: string
  readonly?: boolean
  params: URLSearchParams
  set: (patch: Record<string, string | null>) => void
}) {
  const rev = pickRev(d, params.get('rev'))
  const asked = params.get('tab') ?? ''
  const file = params.get('file')
  // 术语表（本步登记的 > 项目术语表 > 平台内置）：讲解自己会取一份，这里给执行层的文档用
  const termList = useQuery({ queryKey: ['terms', pid, d.step.id, rev.id], queryFn: () => api.terms(pid, d.step.id, rev.id), staleTime: 60_000 })
  const terms = useTerms(termList.data?.terms)
  const openFile = (path: string) => set({ file: path })
  const byKind = useMemo(() => {
    const m: Record<string, typeof rev.files> = {}
    rev.files.forEach((f) => (m[f.kind] ??= []).push(f))
    return m
  }, [rev])
  const plans = [...(byKind.plan_user ?? []), ...(byKind.plan ?? []), ...(byKind.approval ?? []), ...(byKind.planning ?? []).filter((f) => f.rel.endsWith('.md'))]
  // 没指定选项卡时：有讲解就看讲解；只出了计划（还没有讲解）的步骤直接落在执行计划，审批的人不用再点一下
  const fallback: Tab = byKind.guide || !plans.length ? 'guide' : 'plan'
  const tab: Tab = (LEGACY[asked] ?? (['guide', 'board', 'data', 'plan', 'code', 'log', 'products'].includes(asked) ? (asked as Tab) : fallback))
  const code = [...(byKind.notebook ?? []), ...(byKind.code ?? []), ...(byKind.acceptance_code ?? [])]
  const records = byKind.execution_record ?? []
  const item = (key: Tab, label: string, count: number | null = null) => ({
    key, label, count, active: tab === key && !file, onClick: () => set({ tab: key, file: null, open: null, part: null, run: null }),
  })
  const groups: TabGroup[] = [
    { label: '业务层', items: [item('guide', '讲解'), item('board', '看板')] },
    { label: '数据层', items: [item('data', '数据')] },
    { label: '执行层', items: [item('plan', '执行计划', plans.length), item('code', '代码', code.length), item('log', '执行日志'), item('products', '产物')] },
  ]
  // 产物图里的表 → 数据层整张打开
  const openTable = (path: string) => set({ tab: 'data', open: path, file: null })
  const toTab = (t: Tab) => set({ tab: t, file: null, open: null })
  const order = graph ? [...graph.nodes].sort((a, b) => a.order - b.order) : []
  const at = order.findIndex((n) => n.id === d.step.id)
  const prev = at > 0 ? order[at - 1] : null
  const next = at >= 0 && at < order.length - 1 ? order[at + 1] : null
  const common = { pid, root, openFile }
  // 告诉答疑对话框：用户现在停在哪一步、哪一轮、哪个选项卡、看的是哪个文件
  useAskScope({ step: d.step.id, rev: rev.id, tab, file: file ?? planFile(tab, plans, code, records) })

  return (
    <>
      <header className="mb-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-bold">
            {d.step.id} · {d.step.title}
          </h1>
          <StatusBadge status={d.step.status} />
          {d.stage && (
            <Link to={`/p/${pid}/stage/${d.stage.id}`} className="rounded px-1.5 text-[11px] hover:underline" style={{ color: d.stage.color, border: `1px solid ${d.stage.color}` }}>
              {d.stage.name}
            </Link>
          )}
          <span className="ml-auto flex gap-1 text-xs">
            {prev && (
              <Link to={`/p/${pid}/steps/${prev.id}`} className="inline-flex items-center gap-0.5 rounded border border-slate-300 px-2 py-0.5 text-slate-600 hover:bg-slate-50" title={`上一步：${prev.id} ${prev.title}`}>
                <ArrowLeft className="h-3 w-3" aria-hidden />
                {prev.id}
              </Link>
            )}
            {next && (
              <Link to={`/p/${pid}/steps/${next.id}`} className="inline-flex items-center gap-0.5 rounded border border-slate-300 px-2 py-0.5 text-slate-600 hover:bg-slate-50" title={`下一步：${next.id} ${next.title}`}>
                {next.id}
                <ArrowRight className="h-3 w-3" aria-hidden />
              </Link>
            )}
          </span>
        </div>
        {d.revisions.length > 1 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs" role="tablist" aria-label="轮次">
            <span className="text-slate-500">轮次</span>
            {d.revisions.map((r) => (
              <button
                key={r.id}
                role="tab"
                aria-selected={r.id === rev.id}
                onClick={() => set({ rev: r.id, file: null, open: null, run: null })}
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 ${r.id === rev.id ? 'border-blue-500 bg-blue-50 text-blue-800' : 'border-slate-300 bg-white hover:bg-slate-50'}`}
                title={`${r.status_label}${r.date ? ` · ${r.date}` : ''}${r.summary ? `：${r.summary}` : ''}`}
              >
                <span className="h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[r.status] }} aria-hidden />
                {r.id}
                {r.is_current && <span className="text-[10px] text-slate-500">当前</span>}
              </button>
            ))}
            <span className="text-slate-500">
              正在看 {rev.id}：{rev.status_label}
              {rev.date ? `，${fmtTime(rev.date)}` : ''}
              {rev.summary ? `。${rev.summary}` : ''}
            </span>
          </div>
        )}
      </header>
      <ApprovalBar pid={pid} d={d} revId={rev.id} readonly={readonly} onTab={toTab} />
      <TabGroups groups={groups} className="mb-3" />
      {file ? (
        <FileViewer pid={pid} path={file} projectRoot={root} onOpenFile={openFile} onClose={() => set({ file: null })} terms={terms} />
      ) : (
        <>
          {tab === 'guide' && <GuideView {...common} d={d} rev={rev} part={params.get('part')} cell={params.get('cell')} onTab={toTab} />}
          {tab === 'board' && <StepBoard pid={pid} root={root} d={d} rev={rev} onTab={toTab} />}
          {tab === 'data' && <StepTables pid={pid} stepId={d.step.id} revId={rev.id} open={params.get('open')} onOpen={(p) => set({ open: p })} />}
          {tab === 'plan' && <DocTabs {...common} terms={terms} files={plans} empty="这一轮还没有计划文件（计划、审批记录）。" />}
          {tab === 'code' && <DocTabs {...common} terms={terms} files={code} labelOf={(f) => f.rel} empty="这一轮还没有代码或 notebook。" />}
          {tab === 'products' && <StepProducts pid={pid} d={d} rev={rev} onOpenTable={openTable} openFile={openFile} />}
          {tab === 'log' && (
            <div className="space-y-3">
              <StepRuns pid={pid} stepId={d.step.id} runId={params.get('run')} onOpen={(r) => set({ run: r })} />
              {records.length > 0 && (
                <section>
                  <h3 className="mb-1.5 text-xs tracking-wider text-slate-400">执行记录文件</h3>
                  <DocTabs {...common} terms={terms} files={records} labelOf={(f) => f.rel} empty="" />
                </section>
              )}
            </div>
          )}
        </>
      )}
    </>
  )
}
