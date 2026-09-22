import { Link } from 'react-router'
import type { Graph } from '../types'

const WAITING = new Set(['pending_approval', 'awaiting_acceptance'])

/** 生命周期条：11 个阶段按顺序排开，每格写完成几步、待你处理几步；点一格进入该阶段板块。 */
export default function LifecycleStrip({ pid, graph }: { pid: string; graph: Graph }) {
  return (
    <ol className="flex gap-1 overflow-x-auto pb-1" aria-label="生命周期进度">
      {graph.stages.map((s) => {
        const steps = graph.nodes.filter((n) => n.stage === s.id)
        const done = steps.filter((n) => n.status === 'done').length
        const waiting = steps.filter((n) => WAITING.has(n.status)).length
        return (
          <li key={s.id} className="min-w-[6.25rem] flex-1">
            <Link
              to={`/p/${pid}/stage/${s.id}`}
              className={`block rounded-md border px-2 py-1 hover:border-blue-300 ${steps.length ? 'border-slate-200 bg-white' : 'border-dashed border-slate-200 bg-slate-50 text-slate-400'}`}
              title={steps.length ? `${s.name}：完成 ${done}/${steps.length} 步${waiting ? `，${waiting} 步等你处理` : ''}` : `${s.name}：还没有登记步骤`}
            >
              <span className="block truncate text-[11px] font-medium">{s.name}</span>
              <span className="mt-1 block h-1 overflow-hidden rounded-full bg-slate-100" aria-hidden>
                <span className="block h-full rounded-full" style={{ width: steps.length ? `${(done / steps.length) * 100}%` : 0, background: s.color }} />
              </span>
              <span className="tabular mt-0.5 block text-[10.5px] text-slate-500">
                {steps.length ? `完成 ${done}/${steps.length}${waiting ? ` · 待你 ${waiting}` : ''}` : '未开始'}
              </span>
            </Link>
          </li>
        )
      })}
    </ol>
  )
}
