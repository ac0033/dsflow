import { Link } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, BookOpen, CheckCircle2, PauseCircle, Table2 } from 'lucide-react'
import { api } from '../../api'
import AlertList from '../../components/AlertList'
import StatusBadge, { STATUS_LABEL } from '../../components/StatusBadge'
import { useScope } from '../../lib/scope'
import type { Edge, Stage, StepNode, StepStatus } from '../../types'
import { Block } from '../board/BoardPage'

const ORDER: StepStatus[] = ['done', 'awaiting_acceptance', 'in_progress', 'partial', 'pending_approval', 'stopped', 'pending']

/**
 * 阶段概况：先说要不要你处理，再按顺序给每一步「讲解的开头」——目的一句、结论一句、能不能继续。
 * 结论来自各步的讲解（讲给人听的话）；还没有讲解的步骤退回这一步登记的目的与结论，并标明暂未讲解。
 * 数字、决策、动态都不在这里堆：数字在各步讲解里有出处，动态在总览看板。
 */
export default function StageOverview() {
  const { pid, stage, stepIds } = useScope()
  const project = useQuery({ queryKey: ['project', pid], queryFn: () => api.project(pid) })
  const board = useQuery({ queryKey: ['board', pid], queryFn: () => api.board(pid), refetchInterval: 20000 })
  const graph = project.data?.graph
  if (!graph || !stage || !stepIds) return null
  const steps = graph.nodes.filter((n) => n.stage === stage.id).sort((a, b) => a.order - b.order)

  if (!steps.length)
    return (
      <div className="mx-auto max-w-5xl px-6 py-4">
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm leading-relaxed text-slate-600">
          这个阶段还没有登记步骤。在 <code className="rounded bg-slate-100 px-1">lifecycle/steps.json</code> 里登记 <code className="rounded bg-slate-100 px-1">stage: {stage.id}</code>{' '}
          的步骤（目录放在 <code className="rounded bg-slate-100 px-1">{stage.dir}/</code> 下），这里就会按顺序列出每一步的目的与结论。
        </div>
      </div>
    )

  const b = board.data
  const mine = <T extends { step?: string | null }>(xs: T[] | undefined) => (xs ?? []).filter((x) => !!x.step && stepIds.has(x.step))
  const alerts = mine(b?.alerts)
  const a = b?.attention
  const waitingApproval = mine(a?.pending_approval)
  const waitingAcceptance = mine(a?.awaiting_acceptance)
  const blockingDecisions = mine(a?.blocking_decisions)
  const openIssues = mine(a?.open_issues)
  const needs = (
    [
      ['待审批', waitingApproval.length],
      ['待验收', waitingAcceptance.length],
      ['阻塞后续的待决事项', blockingDecisions.length],
      ['阻塞的问题', openIssues.filter((i) => i.blocking).length],
    ] as [string, number][]
  ).filter(([, n]) => n)
  const severe = alerts.filter((x) => x.level === 'critical' || x.level === 'serious').length
  const counts = ORDER.filter((s) => steps.some((n) => n.status === s)).map((s) => `${STATUS_LABEL[s]} ${steps.filter((n) => n.status === s).length}`)
  const headline = severe
    ? `本阶段有 ${severe} 条严重或重要告警，先处理再继续。`
    : needs.length
      ? `需要你处理：${needs.map(([k, n]) => `${k} ${n} 项`).join('、')}。`
      : steps.every((s) => s.status === 'done')
        ? '本阶段的步骤都已完成。'
        : '本阶段目前没有等你审批、验收或裁定的事项。'

  return (
    <div className="mx-auto max-w-5xl space-y-4 px-6 py-4">
      <section className={`rounded-lg border p-4 ${severe ? 'border-red-300 bg-red-50' : needs.length ? 'border-amber-200 bg-amber-50/60' : 'border-green-200 bg-green-50/60'}`}>
        <p className="text-base font-semibold leading-relaxed">{headline}</p>
        <p className="mt-1 text-sm text-slate-700">
          {steps.length} 步：{counts.join('、')}。{alerts.length ? `本阶段告警 ${alerts.length} 条。` : ''}
        </p>
      </section>

      {alerts.length > 0 && (
        <Block title={`本阶段告警（${alerts.length}）`}>
          <AlertList pid={pid} alerts={alerts} />
        </Block>
      )}

      <section>
        <h2 className="mb-2 text-sm font-semibold">
          每一步在回答什么、答案是什么
        </h2>
        <ol className="space-y-2">
          {steps.map((s) => (
            <StepLine key={s.id} pid={pid} step={s} stage={stage} />
          ))}
        </ol>
      </section>

      {(blockingDecisions.length > 0 || openIssues.length > 0) && (
        <details className="rounded-lg border border-slate-200 bg-white px-3 py-2">
          <summary className="cursor-pointer text-sm font-semibold">
            本阶段未解决的问题与待决事项
            <span className="ml-2 text-xs font-normal text-slate-500">
              问题 {openIssues.length} 个 · 阻塞后续的待决事项 {blockingDecisions.length} 项
            </span>
            <Link to={`/p/${pid}/tracker`} className="ml-3 text-xs font-normal text-blue-700 underline">
              去处理
            </Link>
          </summary>
          <ul className="mt-2 space-y-1 text-sm">
            {openIssues.map((i) => (
              <li key={i.id}>
                <span className="font-mono text-xs text-slate-500">{i.id}</span> {i.title}
                <span className="ml-1 text-[11px] text-slate-500">
                  {i.severity}
                  {i.blocking ? ' · 阻塞' : ''} · {i.step}
                </span>
              </li>
            ))}
            {blockingDecisions.map((p) => (
              <li key={`${p.source ?? 'p'}-${p.id}`}>
                <span className="font-mono text-xs text-slate-500">{p.id}</span> {p.question}
                <span className="ml-1 text-[11px] text-amber-800">阻塞 · {p.step}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <Links pid={pid} steps={steps} nodes={graph.nodes} edges={graph.edges} />
    </div>
  )
}

/** 一步一行：目的 → 结论（能否继续），右边是讲解 / 数据两个入口。 */
function StepLine({ pid, step, stage }: { pid: string; step: StepNode; stage: Stage }) {
  const brief = step.brief
  const question = brief?.question || step.op
  const answer = brief?.answer || step.card?.headline || step.headline || step.finding
  const can = brief ? brief.can_continue : (step.card?.can_continue ?? null)
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-3" style={{ borderLeft: `4px solid ${stage.color}` }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-slate-500">{step.id}</span>
        <Link to={`/p/${pid}/steps/${step.id}`} className="text-sm font-semibold hover:text-blue-700 hover:underline">
          {step.title}
        </Link>
        <StatusBadge status={step.status} />
        {step.current_revision && (
          <span className="rounded bg-slate-100 px-1.5 py-px text-[11px] text-slate-600">
            {step.current_revision}
            {step.revision_count > 1 ? ` · 共 ${step.revision_count} 轮` : ''}
          </span>
        )}
        {step.issue_count > 0 && <span className="rounded bg-red-100 px-1.5 py-px text-[11px] text-red-700">{step.issue_count} 个校验问题</span>}
        {!brief && <span className="rounded bg-amber-50 px-1.5 py-px text-xs text-amber-800 ring-1 ring-amber-200">暂未讲解</span>}
        <span className="ml-auto flex gap-1">
          <Link to={`/p/${pid}/steps/${step.id}`} className="inline-flex items-center gap-1 rounded bg-blue-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-blue-700">
            <BookOpen className="h-3 w-3" aria-hidden />
            讲解
          </Link>
          <Link to={`/p/${pid}/steps/${step.id}?tab=data`} className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50">
            <Table2 className="h-3 w-3" aria-hidden />
            数据
          </Link>
        </span>
      </div>
      <dl className="mt-2 grid gap-x-3 gap-y-1 text-sm leading-relaxed sm:grid-cols-[3rem_1fr]">
        <dt className="text-xs text-slate-500 sm:pt-0.5">目的</dt>
        <dd className="text-slate-700">{question || <span className="text-slate-400">没有写</span>}</dd>
        <dt className="text-xs text-slate-500 sm:pt-0.5">结论</dt>
        <dd className="font-medium text-slate-900">
          {can === true && (
            <span className="mr-1.5 inline-flex items-center gap-0.5 rounded-full bg-green-100 px-1.5 py-px align-text-bottom text-[11px] font-medium text-green-800">
              <CheckCircle2 className="h-3 w-3" aria-hidden />
              可以继续
            </span>
          )}
          {can === false && (
            <span className="mr-1.5 inline-flex items-center gap-0.5 rounded-full bg-amber-100 px-1.5 py-px align-text-bottom text-[11px] font-medium text-amber-900">
              <PauseCircle className="h-3 w-3" aria-hidden />
              暂不能继续
            </span>
          )}
          {answer || <span className="font-normal text-slate-400">还没有结论</span>}
        </dd>
      </dl>
    </li>
  )
}

function Links({ pid, steps, nodes, edges }: { pid: string; steps: StepNode[]; nodes: StepNode[]; edges: Edge[] }) {
  const ids = new Set(steps.map((s) => s.id))
  const title = new Map(nodes.map((n) => [n.id, n.title]))
  const deps = edges.filter((e) => e.type !== 'revision_loop')
  const upstream = deps.filter((e) => !ids.has(e.from) && ids.has(e.to))
  const downstream = deps.filter((e) => ids.has(e.from) && !ids.has(e.to))
  if (!upstream.length && !downstream.length) return null
  const item = (e: Edge, dir: 'in' | 'out') => (
    <li key={`${dir}-${e.from}-${e.to}`} className="flex items-start gap-1.5">
      {dir === 'in' ? (
        <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
      ) : (
        <ArrowLeft className="mt-0.5 h-3.5 w-3.5 shrink-0 rotate-180 text-slate-400" aria-hidden />
      )}
      <span>
        <Link to={`/p/${pid}/steps/${e.from}`} className="text-blue-700 hover:underline">
          {e.from} {title.get(e.from)}
        </Link>
        {' → '}
        <Link to={`/p/${pid}/steps/${e.to}`} className="text-blue-700 hover:underline">
          {e.to} {title.get(e.to)}
        </Link>
        <span className="text-slate-500">：{e.label || '未写说明'}</span>
        {e.type === 'back' && <span className="ml-1 text-red-700">（回退）</span>}
      </span>
    </li>
  )
  return (
    <Block title="和其他阶段的衔接">
      <div className="grid gap-3 text-sm md:grid-cols-2">
        <div>
          <p className="mb-1 text-xs font-semibold text-slate-500">上游（交给本阶段）</p>
          {upstream.length ? <ul className="space-y-1">{upstream.map((e) => item(e, 'in'))}</ul> : <p className="text-xs text-slate-400">没有</p>}
        </div>
        <div>
          <p className="mb-1 text-xs font-semibold text-slate-500">下游（本阶段交出去）</p>
          {downstream.length ? <ul className="space-y-1">{downstream.map((e) => item(e, 'out'))}</ul> : <p className="text-xs text-slate-400">没有</p>}
        </div>
      </div>
    </Block>
  )
}
