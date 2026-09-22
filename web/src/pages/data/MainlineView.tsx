import { Link } from 'react-router'
import { useQueries } from '@tanstack/react-query'
import { ArrowRight, BookOpen } from 'lucide-react'
import { api } from '../../api'
import { fmtInt } from '../../lib/format'
import type { Stage, StepNode, StepStock, StepTable } from '../../types'

/**
 * 数据主线：按执行顺序，每一步的存量账——执行前有几张有用的表，这一步新增 / 更新 / 退出了什么，执行后剩几张。
 * 三个层级用的是同一个视图与同一份来源（每步的 stock）：项目总览看全部步骤，阶段看本阶段，步骤页「数据」是全貌。
 * 点一张表就到那一步整张打开它。
 */
export default function MainlineView({ pid, steps, stages, groupByStage = false }: {
  pid: string
  steps: StepNode[]
  stages: Stage[]
  /** 项目总览按阶段分组；阶段板块不用分 */
  groupByStage?: boolean
}) {
  const stocks = useQueries({
    queries: steps.map((s) => ({
      queryKey: ['stock', pid, s.id, s.current_revision ?? ''],
      queryFn: () => api.stepStock(pid, s.id, s.current_revision),
      staleTime: 60_000,
    })),
  })
  if (!steps.length) return <p className="text-sm text-slate-500">还没有登记步骤。</p>
  const color = new Map(stages.map((s) => [s.id, s.color]))
  const row = (s: StepNode, i: number) => (
    <StepRow key={s.id} pid={pid} step={s} d={stocks[i]?.data} error={stocks[i]?.error as Error | undefined} color={color.get(s.stage) ?? '#94a3b8'} />
  )
  const groups = groupByStage
    ? stages.map((st) => ({ stage: st, items: steps.map((s, i) => [s, i] as const).filter(([s]) => s.stage === st.id) })).filter((g) => g.items.length)
    : [{ stage: null, items: steps.map((s, i) => [s, i] as const) }]

  return (
    <div className="space-y-3">
      {groups.map((g) => (
        <section key={g.stage?.id ?? 'all'}>
          {g.stage && (
            <h2 className="mb-1.5 flex items-center gap-2 text-sm font-semibold" style={{ color: g.stage.color }}>
              {g.stage.name}
              <Link to={`/p/${pid}/stage/${g.stage.id}/data`} className="text-xs font-normal text-blue-700 hover:underline">
                本阶段
              </Link>
            </h2>
          )}
          <ol className="space-y-2">{g.items.map(([s, i]) => row(s, i))}</ol>
        </section>
      ))}
    </div>
  )
}

const CHIP: Record<string, string> = {
  新增: 'bg-blue-600 text-white ring-blue-600 hover:bg-blue-700',
  更新: 'bg-amber-400 text-amber-950 ring-amber-400 hover:bg-amber-500',
  退出: 'bg-white text-slate-500 ring-slate-300 line-through hover:bg-slate-50',
  核对: 'bg-white text-slate-800 ring-slate-300 hover:bg-slate-50',
  读取: 'bg-white text-slate-800 ring-slate-300 hover:bg-slate-50',
}

function Chip({ pid, step, t }: { pid: string; step: string; t: StepTable }) {
  const out = t.role === '新增' || t.role === '更新'
  return (
    <Link
      to={`/p/${pid}/steps/${step}?tab=data&open=${encodeURIComponent(t.path)}`}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs ring-1 ${CHIP[t.role] ?? CHIP['读取']}`}
      title={`${t.role} · ${t.path}${t.ready ? ` · ${fmtInt(t.rows ?? 0)} 行 × ${t.columns} 列` : ''}${t.retired_by ? `\n被 ${t.retired_by} 替代` : ''}`}
    >
      {t.name}
      {t.ready && t.role !== '退出' && (
        <span className={`tabular text-[10.5px] ${out ? 'opacity-80' : 'text-slate-500'}`}>
          {fmtInt(t.rows ?? 0)}×{t.columns}
        </span>
      )}
      {out && t.diff?.known && t.diff.added.length > 0 && <span className="rounded bg-white/80 px-1 text-[10px] text-amber-950">+{t.diff.added.length} 列</span>}
    </Link>
  )
}

function StepRow({ pid, step, d, error, color }: { pid: string; step: StepNode; d?: StepStock; error?: Error; color: string }) {
  const delta = d?.delta
  return (
    <li className="rounded-lg border border-slate-200 bg-white px-3 py-2" style={{ borderLeft: `4px solid ${color}` }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-slate-500">{step.id}</span>
        <Link to={`/p/${pid}/steps/${step.id}?tab=data`} className="text-sm font-semibold hover:text-blue-700 hover:underline">
          {step.title}
        </Link>
        <Link to={`/p/${pid}/steps/${step.id}`} className="ml-auto inline-flex items-center gap-1 text-xs text-blue-700 hover:underline">
          <BookOpen className="h-3 w-3" aria-hidden />
          讲解
        </Link>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-600">
        {error && <span className="text-red-600">{error.message}</span>}
        {!d && !error && <span className="text-slate-400">读取…</span>}
        {d && delta && d.changes_data && (
          <>
            <span className="tabular rounded bg-slate-100 px-1.5 py-0.5 text-slate-600" title="执行前有几张有用的表">{d.before.length} 张</span>
            <ArrowRight className="h-3.5 w-3.5 text-blue-500" aria-hidden />
            {[...delta.added, ...delta.updated, ...delta.retired].map((t) => (
              <Chip key={`${t.role}-${t.path}`} pid={pid} step={step.id} t={t} />
            ))}
            <ArrowRight className="h-3.5 w-3.5 text-blue-500" aria-hidden />
            <span className="tabular rounded bg-slate-100 px-1.5 py-0.5 text-slate-600" title="执行后剩几张有用的表">{d.after.length} 张</span>
          </>
        )}
        {d && delta && !d.changes_data && delta.checked.length > 0 && (
          <>
            <span>没有增减，只核对了</span>
            {delta.checked.map((t) => (
              <Chip key={t.path} pid={pid} step={step.id} t={t} />
            ))}
          </>
        )}
        {d && delta && !d.changes_data && !delta.checked.length && (
          <span className="text-slate-400">{delta.others.length ? '没有增减数据表，产物是规则与文档。' : '还没有和任何数据表挂钩。'}</span>
        )}
      </div>
    </li>
  )
}
