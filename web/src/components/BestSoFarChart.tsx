import { useState } from 'react'
import { fmtNum, fmtSignedPct } from '../lib/format'
import { SERIES, useWidth } from './charts'

export interface BestPoint {
  label: string
  value: number
  best: number
  gain: number | null
  note?: string
}

/**
 * 历史最好成绩曲线：每次尝试的结果画点（系列 1），到这次为止的最好成绩画阶梯线（系列 2）。
 * 横轴是尝试顺序；纵轴按数据范围取，不从 0 起（看的是提升幅度）。悬停看每次的提升，数值表是全部数字。
 */
export default function BestSoFarChart({ points, height = 170, valueName = '本次结果', bestName = '历史最好' }: {
  points: BestPoint[]
  height?: number
  valueName?: string
  bestName?: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const m = { top: 10, right: 12, bottom: 22, left: 56 }
  const plotW = Math.max(0, width - m.left - m.right)
  const plotH = height - m.top - m.bottom
  const values = points.flatMap((p) => [p.value, p.best])
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  const pad = hi === lo ? Math.abs(hi) * 0.05 || 1 : (hi - lo) * 0.08
  lo -= pad
  hi += pad
  const n = points.length
  const x = (i: number) => m.left + (n <= 1 ? plotW / 2 : (plotW * i) / (n - 1))
  const y = (v: number) => m.top + plotH - ((v - lo) / (hi - lo)) * plotH
  const ticks = [lo + pad, (lo + hi) / 2, hi - pad]
  const best = points.map((p, i) => (i ? `H${x(i)}V${y(p.best)}` : `M${x(0)},${y(p.best)}`)).join('')
  const labelStep = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(plotW / 48))))

  return (
    <figure className="m-0">
      <div className="mb-1 flex flex-wrap gap-3 text-[11px] text-[var(--viz-ink-2)]">
        <span className="inline-flex items-center gap-1">
          <svg width="10" height="10" aria-hidden>
            <circle cx="5" cy="5" r="4" fill={SERIES[0]} />
          </svg>
          {valueName}
        </span>
        <span className="inline-flex items-center gap-1">
          <svg width="14" height="10" aria-hidden>
            <line x1="0" x2="14" y1="5" y2="5" stroke={SERIES[1]} strokeWidth="2" />
          </svg>
          {bestName}
        </span>
      </div>
      <div ref={ref} className="relative" onMouseLeave={() => setHover(null)}>
        {width > 0 && (
          <svg width={width} height={height} role="img" aria-label={`${valueName}与${bestName}，共 ${n} 次尝试`}>
            {ticks.map((t, i) => (
              <g key={i}>
                <line x1={m.left} x2={m.left + plotW} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" strokeWidth={1} />
                <text x={m.left - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill="var(--viz-muted)" className="tabular">
                  {fmtNum(t, 4)}
                </text>
              </g>
            ))}
            {points.map((p, i) =>
              i % labelStep === 0 || i === n - 1 ? (
                <text key={i} x={x(i)} y={height - 6} textAnchor="middle" fontSize={10} fill="var(--viz-muted)">
                  {p.label}
                </text>
              ) : null,
            )}
            {hover != null && <line x1={x(hover)} x2={x(hover)} y1={m.top} y2={m.top + plotH} stroke="var(--viz-axis)" strokeWidth={1} />}
            <path d={best} fill="none" stroke={SERIES[1]} strokeWidth={2} strokeLinejoin="round" />
            {points.map((p, i) => (
              <circle key={i} cx={x(i)} cy={y(p.value)} r={hover === i ? 5 : 4} fill={SERIES[0]} stroke="var(--viz-surface)" strokeWidth={2} />
            ))}
            {points.map((p, i) => {
              const half = n <= 1 ? plotW / 2 : plotW / (n - 1) / 2
              return (
                <rect
                  key={i}
                  x={x(i) - half}
                  y={m.top}
                  width={half * 2}
                  height={plotH}
                  fill="transparent"
                  tabIndex={0}
                  aria-label={`${p.label}：${valueName} ${fmtNum(p.value, 4)}，${bestName} ${fmtNum(p.best, 4)}`}
                  onMouseEnter={() => setHover(i)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                  className="outline-none"
                />
              )
            })}
          </svg>
        )}
        {hover != null && width > 0 && (
          <div
            className="pointer-events-none absolute z-10 w-56 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-[11px] shadow-md"
            style={{ left: Math.min(width - 230, Math.max(0, x(hover) - 110)), top: 0 }}
          >
            <div className="mb-0.5 text-[var(--viz-ink-2)]">{points[hover].label}</div>
            <div className="tabular">
              {valueName} <b>{fmtNum(points[hover].value, 4)}</b>
            </div>
            <div className="tabular">
              {bestName} <b>{fmtNum(points[hover].best, 4)}</b>
            </div>
            <div className="tabular">相对之前最好：{points[hover].gain == null ? '—（第一次）' : fmtSignedPct(points[hover].gain, 2)}</div>
            {points[hover].note && <div className="mt-0.5 text-slate-500">{points[hover].note}</div>}
          </div>
        )}
      </div>
      <details className="mt-1 text-[11px]">
        <summary className="cursor-pointer text-slate-500">数值表</summary>
        <table className="tabular mt-1 w-full">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="pr-3 font-normal">尝试</th>
              <th className="pr-3 text-right font-normal">{valueName}</th>
              <th className="pr-3 text-right font-normal">{bestName}</th>
              <th className="pr-3 text-right font-normal">相对之前最好</th>
              <th className="font-normal">假设</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="pr-3">{p.label}</td>
                <td className="pr-3 text-right">{fmtNum(p.value, 4)}</td>
                <td className="pr-3 text-right">{fmtNum(p.best, 4)}</td>
                <td className="pr-3 text-right">{p.gain == null ? '—' : fmtSignedPct(p.gain, 2)}</td>
                <td className="text-slate-600">{p.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  )
}
