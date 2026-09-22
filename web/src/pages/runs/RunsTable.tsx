import { RunStatusBadge, ValidityBadge } from '../../components/RunBadges'
import { fmtDuration, fmtNum, fmtTime } from '../../lib/format'
import type { Run } from '../../types'

const SOURCE: Record<string, string> = { cli: '命令行', sdk: '脚本', ui: '平台重跑' }

/** 运行列表：每行先给假设与结论，再给关键指标；可多选用来对比。 */
export default function RunsTable({ runs, showStep, selected, onToggle, onOpen, active }: {
  runs: Run[]
  showStep?: boolean
  selected?: Set<string>
  onToggle?: (id: string) => void
  onOpen: (id: string) => void
  active?: string | null
}) {
  if (!runs.length) return null
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="w-full text-xs">
        <thead className="bg-slate-50 text-left text-[11px] text-slate-500">
          <tr>
            {onToggle && <th className="w-8 px-2 py-1.5 font-normal" aria-label="选择" />}
            <th className="px-2 py-1.5 font-normal">开始时间</th>
            {showStep && <th className="px-2 py-1.5 font-normal">步骤</th>}
            <th className="px-2 py-1.5 font-normal">状态</th>
            <th className="px-2 py-1.5 font-normal">有效性</th>
            <th className="px-2 py-1.5 font-normal">假设 → 结论</th>
            <th className="px-2 py-1.5 font-normal">指标</th>
            <th className="px-2 py-1.5 text-right font-normal">用时</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr
              key={r.run_id}
              onClick={() => onOpen(r.run_id)}
              className={`cursor-pointer border-t border-slate-100 align-top hover:bg-slate-50 ${active === r.run_id ? 'bg-blue-50' : ''}`}
            >
              {onToggle && (
                <td className="px-2 py-1.5" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" aria-label={`选择 ${r.run_id}`} checked={selected?.has(r.run_id) ?? false} onChange={() => onToggle(r.run_id)} />
                </td>
              )}
              <td className="tabular whitespace-nowrap px-2 py-1.5">
                {fmtTime(r.started_at)}
                <div className="text-[10px] text-slate-400">
                  {SOURCE[r.source] ?? r.source}
                  {r.rerun_of ? ' · 重跑' : ''}
                </div>
              </td>
              {showStep && <td className="whitespace-nowrap px-2 py-1.5 font-mono">{r.step}</td>}
              <td className="whitespace-nowrap px-2 py-1.5">
                <RunStatusBadge status={r.status} />
              </td>
              <td className="whitespace-nowrap px-2 py-1.5">
                <ValidityBadge validity={r.validity} />
              </td>
              <td className="min-w-[260px] max-w-[420px] px-2 py-1.5">
                {r.hypothesis && <p className="truncate text-slate-500" title={r.hypothesis}>假设：{r.hypothesis}</p>}
                <p className="truncate font-medium" title={r.conclusion || r.error || ''}>
                  {r.conclusion || (r.status === 'failed' ? <span className="text-red-700">{r.error || '失败'}</span> : <span className="text-slate-400">没有记录结论</span>)}
                </p>
              </td>
              <td className="px-2 py-1.5">
                <div className="flex min-w-[180px] max-w-[260px] flex-wrap gap-1">
                  {Object.entries(r.metrics)
                    .slice(0, 3)
                    .map(([k, v]) => (
                      <span key={k} className="tabular rounded bg-slate-100 px-1 text-[10.5px]">
                        {k}={v == null ? '—' : fmtNum(v, 4)}
                      </span>
                    ))}
                  {Object.keys(r.fold_metrics).length > 0 && <span className="text-[10.5px] text-slate-500">{Object.keys(r.fold_metrics).length} 折</span>}
                </div>
              </td>
              <td className="tabular whitespace-nowrap px-2 py-1.5 text-right">{fmtDuration(r.duration_s)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
