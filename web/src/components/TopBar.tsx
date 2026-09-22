import { useEffect, useRef, useState } from 'react'
import { Link, useMatch, useNavigate } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { Check, ChevronDown, ChevronRight, FolderPlus, Lock, Menu, Workflow } from 'lucide-react'
import { api } from '../api'
import { useNav } from '../lib/nav'
import ImportProjectForm from './ImportProjectForm'

/** 顶栏：DSFlow → 项目切换（含导入）→ 当前阶段 › 当前步骤。 */
export default function TopBar() {
  const pid = useMatch('/p/:id/*')?.params.id
  const stageMatch = useMatch('/p/:id/stage/:stageId/*')
  const stepMatch = useMatch('/p/:id/steps/:stepId')
  const { setOpen } = useNav()
  const project = useQuery({ queryKey: ['project', pid], queryFn: () => api.project(pid!), enabled: !!pid })
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, staleTime: Infinity })
  const graph = project.data?.graph
  const step = stepMatch ? graph?.nodes.find((n) => n.id === stepMatch.params.stepId) : undefined
  const stageId = stageMatch?.params.stageId ?? (step ? String(step.stage) : undefined)
  const stage = graph?.stages.find((s) => String(s.id) === stageId)

  return (
    <header className="flex h-12 shrink-0 items-center gap-1.5 border-b border-slate-200 bg-white px-3">
      {pid && (
        <button onClick={() => setOpen(true)} aria-label="打开阶段菜单" className="rounded p-1 text-slate-600 hover:bg-slate-100 md:hidden">
          <Menu className="h-5 w-5" />
        </button>
      )}
      <Link to="/" className="flex shrink-0 items-center gap-1.5 pr-1" title="全部项目">
        <Workflow className="h-5 w-5 text-blue-600" aria-hidden />
        <span className="hidden text-sm font-bold sm:inline">DSFlow</span>
      </Link>
      <span className="text-slate-300" aria-hidden>
        /
      </span>
      <ProjectSwitcher pid={pid} />
      {pid && !stage && !step && (
        <>
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
          <span className="text-sm text-slate-600">总览</span>
        </>
      )}
      {pid && stage && (
        <>
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
          <Link to={`/p/${pid}/stage/${stage.id}`} className="min-w-0 truncate text-sm text-slate-700 hover:underline">
            {stage.name}
          </Link>
        </>
      )}
      {step && (
        <>
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
          <span className="min-w-0 truncate text-sm">
            <span className="font-mono text-xs text-slate-500">{step.id}</span> {step.title}
          </span>
        </>
      )}
      <span className="ml-auto hidden shrink-0 text-[11px] text-slate-400 sm:inline">{health.data ? `v${health.data.version}` : ''}</span>
    </header>
  )
}

function ProjectSwitcher({ pid }: { pid?: string }) {
  const [open, setOpen] = useState(false)
  const [importing, setImporting] = useState(false)
  const [q, setQ] = useState('')
  const box = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const all = projects.data ?? []
  const current = all.find((p) => p.id === pid)
  const list = all.filter((p) => !q || p.name.includes(q) || p.root.toLowerCase().includes(q.toLowerCase()))

  return (
    <div ref={box} className="relative min-w-0">
      <button
        onClick={() => {
          setOpen(!open)
          setImporting(false)
        }}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex max-w-[16rem] items-center gap-1.5 rounded-md px-2 py-1 text-sm hover:bg-slate-100 sm:max-w-[24rem]"
      >
        <span className="truncate font-medium">{current?.name ?? '选择项目'}</span>
        {current?.readonly && <Lock className="h-3 w-3 shrink-0 text-slate-400" aria-label="只读接入" />}
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-500" aria-hidden />
      </button>
      {open && (
        <div role="menu" className="absolute left-0 top-full z-50 mt-1 w-[24rem] max-w-[calc(100vw-1.5rem)] rounded-lg border border-slate-200 bg-white shadow-lg">
          {all.length > 6 && (
            <div className="border-b border-slate-100 p-2">
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="按名称或路径筛选" aria-label="筛选项目" className="w-full rounded border border-slate-300 px-2 py-1 text-sm" />
            </div>
          )}
          <p className="px-3 pb-0.5 pt-2 text-[11px] font-semibold text-slate-500">切换项目</p>
          <ul className="max-h-80 overflow-auto pb-1">
            {list.map((p) => (
              <li key={p.id}>
                <button
                  role="menuitem"
                  onClick={() => {
                    setOpen(false)
                    navigate(`/p/${p.id}`)
                  }}
                  className="flex w-full items-start gap-2 px-3 py-1.5 text-left hover:bg-slate-50"
                >
                  <Check className={`mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-600 ${p.id === pid ? '' : 'invisible'}`} aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1 text-sm">
                      <span className="truncate">{p.name}</span>
                      {p.readonly && <Lock className="h-3 w-3 shrink-0 text-slate-400" aria-label="只读接入" />}
                    </span>
                    <span className="block truncate text-[11px] text-slate-500" title={p.root}>
                      {p.step_count ?? 0} 个步骤 · {p.readonly ? '只读接入' : '可写'}
                      {p.error_count ? ` · ${p.error_count} 个校验问题` : ''} · {p.root}
                    </span>
                  </span>
                </button>
              </li>
            ))}
            {!list.length && <li className="px-3 py-2 text-xs text-slate-500">{all.length ? '没有匹配的项目' : '还没有项目'}</li>}
          </ul>
          <div className="border-t border-slate-200 p-2">
            {importing ? (
              <ImportProjectForm onDone={() => setOpen(false)} />
            ) : (
              <button onClick={() => setImporting(true)} className="flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-sm text-blue-700 hover:bg-blue-50">
                <FolderPlus className="h-4 w-4" aria-hidden />
                导入项目目录…
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
