import { Link } from 'react-router'
import { CircleHelp, Hourglass, OctagonPause, TrendingUp } from 'lucide-react'
import BestSoFarChart from './BestSoFarChart'
import type { StopRule } from '../types'

const LEVEL = {
  stop: { label: '建议判断是否停止', icon: OctagonPause, cls: 'text-amber-900 bg-amber-50 border-amber-200' },
  continue: { label: '仍有提升', icon: TrendingUp, cls: 'text-green-800 bg-green-50 border-green-200' },
  insufficient: { label: '运行次数不够', icon: Hourglass, cls: 'text-slate-700 bg-slate-50 border-slate-200' },
  unknown: { label: '不知道指标方向', icon: CircleHelp, cls: 'text-slate-700 bg-slate-50 border-slate-200' },
}

/** 停止规则卡：同一步骤、同一指标，每次尝试相对之前最好成绩的提升；用在建模阶段的「实验对比」。 */
export default function StopCard({ pid, r }: { pid: string; r: StopRule }) {
  const s = LEVEL[r.level]
  return (
    <article className="rounded border border-slate-200 bg-white p-2.5">
      <div className="mb-1 flex flex-wrap items-center gap-2 text-sm">
        <Link to={`/p/${pid}/steps/${r.step}`} className="font-medium text-blue-700 hover:underline">
          {r.step}
        </Link>
        <span className="font-medium">{r.metric}</span>
        <span className="text-xs text-slate-500">{r.direction === 'min' ? '越小越好' : r.direction === 'max' ? '越大越好' : '方向未知'} · {r.points.length} 次成功运行</span>
      </div>
      <p className={`mb-2 flex items-start gap-1.5 rounded border px-2 py-1 text-[13px] leading-relaxed ${s.cls}`}>
        <s.icon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>
          <b>{s.label}：</b>
          {r.hint}
        </span>
      </p>
      <BestSoFarChart
        points={r.points.map((p, i) => ({ label: `#${i + 1}`, value: p.value, best: p.best, gain: p.gain, note: p.hypothesis }))}
        valueName={`本次 ${r.metric}`}
        bestName="历史最好"
      />
    </article>
  )
}
