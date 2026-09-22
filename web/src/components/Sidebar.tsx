import { useEffect, useState } from 'react'
import { Link, useLocation, useMatch } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, LayoutDashboard, X } from 'lucide-react'
import { api } from '../api'
import { useNav } from '../lib/nav'
import type { Stage, StepNode } from '../types'
import { STATUS_COLOR, STATUS_LABEL } from './StatusBadge'

const WAITING = new Set(['pending_approval', 'awaiting_acceptance'])

/** 左侧菜单：总览 + 生命周期的各个阶段；当前阶段展开它的步骤。 */
export default function Sidebar({ pid }: { pid: string }) {
  const { open, setOpen } = useNav()
  const location = useLocation()
  const project = useQuery({ queryKey: ['project', pid], queryFn: () => api.project(pid) })
  const stageMatch = useMatch('/p/:id/stage/:stageId/*')
  const stepMatch = useMatch('/p/:id/steps/:stepId')
  const graph = project.data?.graph
  const stepNode = stepMatch ? graph?.nodes.find((n) => n.id === stepMatch.params.stepId) : undefined
  const activeStage = stageMatch ? Number(stageMatch.params.stageId) : stepNode?.stage
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  useEffect(() => setOpen(false), [location.pathname, setOpen])
  useEffect(() => {
    if (activeStage != null) setExpanded((s) => (s.has(activeStage) ? s : new Set(s).add(activeStage)))
  }, [activeStage])

  const toggle = (id: number) =>
    setExpanded((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const done = graph?.nodes.filter((n) => n.status === 'done').length ?? 0
  const overviewActive = !stageMatch && !stepMatch

  const body = (
    <nav className="flex h-full flex-col" aria-label="项目导航">
      <div className="p-2">
        <Link
          to={`/p/${pid}`}
          className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-sm ${overviewActive ? 'bg-blue-50 font-medium text-blue-700' : 'text-slate-700 hover:bg-slate-100'}`}
        >
          <LayoutDashboard className="h-4 w-4" aria-hidden />
          总览
        </Link>
      </div>
      <div className="flex items-baseline px-4 pb-1 pt-1">
        <h2 className="text-[11px] font-semibold text-slate-500">生命周期</h2>
        {graph && <span className="ml-auto text-[11px] text-slate-400">完成 {done}/{graph.nodes.length} 步</span>}
      </div>
      <ol className="min-h-0 flex-1 overflow-auto px-2 pb-3">
        {project.isLoading && <li className="px-2 text-xs text-slate-400">加载中…</li>}
        {project.error && <li className="px-2 text-xs text-red-600">{(project.error as Error).message}</li>}
        {graph?.stages.map((stage) => (
          <StageItem
            key={stage.id}
            pid={pid}
            stage={stage}
            steps={graph.nodes.filter((n) => n.stage === stage.id).sort((a, b) => a.order - b.order)}
            active={activeStage === stage.id && !stepMatch}
            containsActive={activeStage === stage.id}
            activeStep={stepMatch?.params.stepId}
            expanded={expanded.has(stage.id)}
            onToggle={() => toggle(stage.id)}
          />
        ))}
      </ol>
    </nav>
  )

  return (
    <>
      <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white md:block">{body}</aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-slate-900/30" onClick={() => setOpen(false)} aria-hidden />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85vw] bg-white pt-8 shadow-xl">
            <button onClick={() => setOpen(false)} aria-label="关闭菜单" className="absolute right-2 top-2 rounded p-1 text-slate-500 hover:bg-slate-100">
              <X className="h-4 w-4" />
            </button>
            {body}
          </aside>
        </div>
      )}
    </>
  )
}

function StageItem({ pid, stage, steps, active, containsActive, activeStep, expanded, onToggle }: {
  pid: string
  stage: Stage
  steps: StepNode[]
  active: boolean
  containsActive: boolean
  activeStep?: string
  expanded: boolean
  onToggle: () => void
}) {
  const done = steps.filter((s) => s.status === 'done').length
  const waiting = steps.filter((s) => WAITING.has(s.status)).length
  const issues = steps.reduce((n, s) => n + s.issue_count, 0)
  const empty = !steps.length
  return (
    <li className="mb-0.5">
      <div className={`flex items-center rounded-md ${active ? 'bg-blue-50' : containsActive ? 'bg-slate-50' : 'hover:bg-slate-100'}`}>
        <button onClick={onToggle} disabled={empty} aria-label={expanded ? '收起步骤' : '展开步骤'} aria-expanded={expanded} className="shrink-0 p-1 pl-1.5 text-slate-400 disabled:invisible">
          <ChevronRight className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`} />
        </button>
        <Link
          to={`/p/${pid}/stage/${stage.id}`}
          className={`flex min-w-0 flex-1 items-center gap-1.5 py-1.5 pr-2 text-sm ${active ? 'font-medium text-blue-700' : empty ? 'text-slate-400' : 'text-slate-700'}`}
          title={empty ? `${stage.name}：还没有登记步骤` : `${stage.name}：完成 ${done}/${steps.length} 步`}
        >
          <span className="h-3.5 w-1 shrink-0 rounded-full" style={{ background: stage.color, opacity: empty ? 0.35 : 1 }} aria-hidden />
          <span className="truncate">{stage.name}</span>
          <span className="ml-auto flex shrink-0 items-center gap-1 text-[11px] font-normal text-slate-400">
            {issues > 0 && (
              <span className="rounded bg-red-100 px-1 text-[10px] text-red-700" title={`${issues} 个校验问题`}>
                校验 {issues}
              </span>
            )}
            {waiting > 0 && (
              <span className="rounded bg-sky-100 px-1 text-[10px] text-sky-800" title={`${waiting} 步等你审批或验收`}>
                待你 {waiting}
              </span>
            )}
            <span className="tabular">{empty ? '—' : `${done}/${steps.length}`}</span>
          </span>
        </Link>
      </div>
      {expanded && !empty && (
        <ol className="mb-1 ml-5 border-l border-slate-200 pl-2">
          {steps.map((s) => (
            <li key={s.id}>
              <Link
                to={`/p/${pid}/steps/${s.id}`}
                className={`flex items-center gap-1.5 rounded px-1.5 py-1 text-[13px] ${activeStep === s.id ? 'bg-blue-50 font-medium text-blue-700' : 'text-slate-600 hover:bg-slate-100'}`}
                title={`${s.id} ${s.title} · ${STATUS_LABEL[s.status]}`}
              >
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: STATUS_COLOR[s.status] }} aria-hidden />
                <span className="sr-only">{STATUS_LABEL[s.status]}</span>
                <span className="font-mono text-[11px] text-slate-400">{s.id}</span>
                <span className="truncate">{s.title}</span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </li>
  )
}
