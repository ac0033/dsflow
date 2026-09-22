import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { fmtDelta, fmtNum, fmtTime } from '../../lib/format'
import type { Run } from '../../types'

const show = (v: unknown) => (v == null ? '—' : typeof v === 'number' ? fmtNum(v, 6) : typeof v === 'object' ? JSON.stringify(v) : String(v))

function meanStd(values: number[]): [number, number] {
  const m = values.reduce((a, b) => a + b, 0) / values.length
  const sd = Math.sqrt(values.reduce((a, b) => a + (b - m) ** 2, 0) / Math.max(1, values.length - 1))
  return [m, sd]
}

function foldStats(r: Run, metric: string): [number, number] | null {
  const vals = Object.values(r.fold_metrics)
    .map((x) => x[metric])
    .filter((x): x is number => x != null)
  return vals.length ? meanStd(vals) : null
}

/** 均值差小于逐折标准差时直接点明：这点差异不足以说明哪一次更好。 */
function NoiseNote({ runs, base, metric }: { runs: Run[]; base: Run; metric: string }) {
  const b = foldStats(base, metric)
  if (!b) return null
  const notes = runs
    .filter((r) => r.run_id !== base.run_id)
    .map((r) => {
      const s = foldStats(r, metric)
      if (!s) return null
      const diff = s[0] - b[0]
      const noise = Math.max(s[1], b[1])
      return { id: r.run_id, diff, noise, small: Math.abs(diff) < noise }
    })
    .filter((x): x is { id: string; diff: number; noise: number; small: boolean } => x != null)
  if (!notes.length) return null
  return (
    <ul className="mt-1 space-y-0.5 text-[11.5px]">
      {notes.map((n) => (
        <li key={n.id} className={n.small ? 'text-amber-800' : 'text-slate-600'}>
          {n.id.slice(9)} 与基线的均值差 {fmtDelta(n.diff)}，
          {n.small
            ? `小于逐折标准差（约 ${fmtNum(n.noise, 1)}）：这点差异在切分带来的波动之内，不足以说明哪一次更好。`
            : `大于逐折标准差（约 ${fmtNum(n.noise, 1)}），差异超出了切分带来的波动。`}
        </li>
      ))}
    </ul>
  )
}

/**
 * 多次运行并排比较：指标给出相对基线的带符号差值；有逐折结果时给均值 ± 标准差，
 * 小幅差值要对照波动来看；参数不同的行高亮；输入数据版本不同时提醒对比可能不公平。
 */
export default function CompareRuns({ runs }: { runs: Run[] }) {
  const [baseId, setBaseId] = useState(runs[runs.length - 1].run_id)
  const base = runs.find((r) => r.run_id === baseId) ?? runs[0]
  const metrics = [...new Set(runs.flatMap((r) => Object.keys(r.metrics)))]
  const params = [...new Set(runs.flatMap((r) => Object.keys(r.params)))]
  const foldMetrics = [...new Set(runs.flatMap((r) => Object.values(r.fold_metrics).flatMap((m) => Object.keys(m))))]
  const inputKey = (r: Run) => r.inputs.map((i) => `${i.name}@${i.version}`).sort().join(',')
  const sameInputs = new Set(runs.map(inputKey)).size <= 1
  const head = (r: Run) => (
    <th key={r.run_id} className="px-2 py-1 text-left font-normal" title={r.hypothesis}>
      <span className="font-mono">{r.run_id.slice(9)}</span>
      {r.run_id === base.run_id && <span className="ml-1 rounded bg-slate-800 px-1 text-[10px] text-white">基线</span>}
      <div className="max-w-[180px] truncate text-[10px] text-slate-400">{r.hypothesis || fmtTime(r.started_at)}</div>
    </th>
  )

  return (
    <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">对比 {runs.length} 次运行</h3>
        <label className="flex items-center gap-1 text-slate-600">
          基线
          <select value={base.run_id} onChange={(e) => setBaseId(e.target.value)} className="rounded border border-slate-300 bg-white px-1 py-0.5">
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id}
              </option>
            ))}
          </select>
        </label>
        <span className="text-slate-500">差值 = 该次运行 − 基线；指标越大越好还是越小越好，要按指标含义判断。</span>
      </div>
      {!sameInputs && (
        <p className="flex items-start gap-1 rounded border border-amber-300 bg-amber-50 px-2 py-1.5 text-amber-900">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          这几次运行用的输入数据版本不同，指标差异可能来自数据变化，而不只是参数或方法变化。
        </p>
      )}

      {metrics.length > 0 && (
        <div className="overflow-x-auto">
          <table className="tabular w-full">
            <thead className="text-[11px] text-slate-500">
              <tr>
                <th className="px-2 py-1 text-left font-normal">指标</th>
                {runs.map(head)}
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => (
                <tr key={m} className="border-t border-slate-100">
                  <td className="px-2 py-1 font-medium">{m}</td>
                  {runs.map((r) => {
                    const v = r.metrics[m]
                    const b = base.metrics[m]
                    return (
                      <td key={r.run_id} className="px-2 py-1">
                        {show(v)}
                        {r.run_id !== base.run_id && v != null && b != null && <span className="ml-1 text-slate-500">（{fmtDelta(v - b)}）</span>}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {foldMetrics.map((m) => {
        const folds = [...new Set(runs.flatMap((r) => Object.keys(r.fold_metrics)))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
        return (
          <div key={m} className="overflow-x-auto">
            <p className="mb-1 font-medium">逐折：{m}</p>
            <table className="tabular w-full">
              <thead className="text-[11px] text-slate-500">
                <tr>
                  <th className="px-2 py-1 text-left font-normal">折</th>
                  {runs.map(head)}
                </tr>
              </thead>
              <tbody>
                {folds.map((f) => (
                  <tr key={f} className="border-t border-slate-100">
                    <td className="px-2 py-1">{f}</td>
                    {runs.map((r) => (
                      <td key={r.run_id} className="px-2 py-1">
                        {show(r.fold_metrics[f]?.[m])}
                      </td>
                    ))}
                  </tr>
                ))}
                <tr className="border-t border-slate-300 font-medium">
                  <td className="px-2 py-1">均值 ± 标准差</td>
                  {runs.map((r) => {
                    const s = foldStats(r, m)
                    return (
                      <td key={r.run_id} className="px-2 py-1">
                        {s ? `${fmtNum(s[0], 4)} ± ${fmtNum(s[1], 4)}` : '—'}
                      </td>
                    )
                  })}
                </tr>
              </tbody>
            </table>
            <NoiseNote runs={runs} base={base} metric={m} />
          </div>
        )
      })}

      {params.length > 0 && (
        <div className="overflow-x-auto">
          <p className="mb-1 font-medium">参数（取值不同的行高亮）</p>
          <table className="w-full">
            <thead className="text-[11px] text-slate-500">
              <tr>
                <th className="px-2 py-1 text-left font-normal">参数</th>
                {runs.map(head)}
              </tr>
            </thead>
            <tbody>
              {params.map((p) => {
                const differs = new Set(runs.map((r) => JSON.stringify(r.params[p]))).size > 1
                return (
                  <tr key={p} className={`border-t border-slate-100 ${differs ? 'bg-amber-50 font-medium' : ''}`}>
                    <td className="px-2 py-1">{p}</td>
                    {runs.map((r) => (
                      <td key={r.run_id} className="px-2 py-1">
                        {show(r.params[p])}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
