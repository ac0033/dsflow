import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { fmtCompact, fmtInt, fmtPct } from '../lib/format'

/*
 * 图表遵循 dataviz 规范：细柱（≤24px、顶端 4px 圆角、底部方角）、相邻柱之间 2px 空隙、
 * 发丝网格线、≥2 个系列才有图例、悬停提示只做补充（每张图都有数值表）。
 */

export const SERIES = ['var(--viz-series-1)', 'var(--viz-series-2)']

export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

function niceMax(v: number): number {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  const n = v / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p
}

export function barPath(x: number, y: number, w: number, h: number): string {
  if (h <= 0 || w <= 0) return ''
  const r = Math.min(4, w / 2, h)
  return `M${x},${y + h}L${x},${y + r}Q${x},${y} ${x + r},${y}L${x + w - r},${y}Q${x + w},${y} ${x + w},${y + r}L${x + w},${y + h}Z`
}

export interface BarSeries {
  name: string
  values: number[]
}

interface BarChartProps {
  labels: string[]
  series: BarSeries[]
  height?: number
  /** 悬停提示与数值表中每一格的标题 */
  describe?: (i: number) => string
  caption?: ReactNode
  valueLabel?: string
}

export function BarChart({ labels, series, height = 170, describe, caption, valueLabel = '行数' }: BarChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const m = { top: 10, right: 8, bottom: 22, left: 44 }
  const plotW = Math.max(0, width - m.left - m.right)
  const plotH = height - m.top - m.bottom
  const n = labels.length
  const max = niceMax(Math.max(0, ...series.flatMap((s) => s.values)))
  const band = n ? plotW / n : 0
  const k = series.length
  const groupW = Math.max(1, band - 2)
  const barW = Math.max(1, Math.min(24, (groupW - 2 * (k - 1)) / k))
  const groupOffset = (band - (barW * k + 2 * (k - 1))) / 2
  const y = (v: number) => m.top + plotH - (v / max) * plotH
  const ticks = [0, max / 2, max]
  const step = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(plotW / 70))))
  const totals = series.map((s) => s.values.reduce((a, b) => a + b, 0))
  const title = (i: number) => (describe ? describe(i) : labels[i])

  return (
    <figure className="m-0">
      {k > 1 && (
        <div className="mb-1 flex flex-wrap gap-3 text-[11px] text-[var(--viz-ink-2)]">
          {series.map((s, i) => (
            <span key={s.name} className="inline-flex items-center gap-1">
              <svg width="10" height="10" aria-hidden>
                <rect width="10" height="10" rx="2" fill={SERIES[i]} />
              </svg>
              {s.name}
            </span>
          ))}
        </div>
      )}
      <div ref={ref} className="relative" onMouseLeave={() => setHover(null)}>
        {width > 0 && (
          <svg width={width} height={height} role="img" aria-label={typeof caption === 'string' ? caption : '柱状图'}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={m.left} x2={m.left + plotW} y1={y(t)} y2={y(t)} stroke={t === 0 ? 'var(--viz-axis)' : 'var(--viz-grid)'} strokeWidth={1} />
                <text x={m.left - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill="var(--viz-muted)" className="tabular">
                  {fmtCompact(t)}
                </text>
              </g>
            ))}
            {labels.map((label, i) =>
              i % step === 0 ? (
                <text key={i} x={m.left + band * i + band / 2} y={height - 6} textAnchor="middle" fontSize={10} fill="var(--viz-muted)">
                  {label.length > 10 ? label.slice(0, 9) + '…' : label}
                </text>
              ) : null,
            )}
            {labels.map((_, i) => (
              <g key={i} opacity={hover == null || hover === i ? 1 : 0.55}>
                {series.map((s, j) => {
                  const v = s.values[i] ?? 0
                  const x = m.left + band * i + groupOffset + j * (barW + 2)
                  return <path key={j} d={barPath(x, y(v), barW, m.top + plotH - y(v))} fill={SERIES[j]} />
                })}
                <rect
                  x={m.left + band * i}
                  y={m.top}
                  width={band}
                  height={plotH}
                  fill="transparent"
                  tabIndex={0}
                  aria-label={`${title(i)}：${series.map((s) => `${s.name} ${fmtInt(s.values[i])}`).join('，')}`}
                  onMouseEnter={() => setHover(i)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                  className="outline-none"
                />
              </g>
            ))}
          </svg>
        )}
        {hover != null && width > 0 && (
          <div
            className="pointer-events-none absolute z-10 min-w-32 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-[11px] shadow-md"
            style={{ left: Math.min(width - 150, Math.max(0, m.left + band * hover + band / 2 - 70)), top: 0 }}
          >
            <div className="mb-0.5 text-[var(--viz-ink-2)]">{title(hover)}</div>
            {series.map((s, j) => (
              <div key={s.name} className="flex items-center gap-1.5">
                <svg width="12" height="4" aria-hidden>
                  <line x1="0" x2="12" y1="2" y2="2" stroke={SERIES[j]} strokeWidth="2" />
                </svg>
                <b className="tabular">{fmtInt(s.values[hover])}</b>
                <span className="text-[var(--viz-muted)]">
                  {k > 1 ? s.name : valueLabel}
                  {totals[j] ? ` · ${fmtPct(s.values[hover] / totals[j])}` : ''}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
      {caption && <figcaption className="mt-1 text-[11px] text-slate-500">{caption}</figcaption>}
      <details className="mt-1 text-[11px]">
        <summary className="cursor-pointer text-slate-500">数值表</summary>
        <div className="max-h-48 overflow-auto">
          <table className="tabular mt-1 w-full">
            <thead className="text-left text-slate-500">
              <tr>
                <th className="pr-3 font-normal">区间 / 取值</th>
                {series.map((s) => (
                  <th key={s.name} className="pr-3 text-right font-normal">
                    {k > 1 ? s.name : valueLabel}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {labels.map((_, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="pr-3">{title(i)}</td>
                  {series.map((s) => (
                    <td key={s.name} className="pr-3 text-right">
                      {fmtInt(s.values[i])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  )
}

/** 表格里的迷你柱：不画坐标轴，精确数字在详情里。 */
export function MiniBars({ values, label, width = 120, height = 26 }: { values: number[]; label: string; width?: number; height?: number }) {
  if (!values.length) return null
  const max = Math.max(1, ...values)
  const bw = width / values.length
  const gap = bw > 4 ? 1 : 0
  return (
    <svg width={width} height={height} role="img" aria-label={label}>
      <title>{label}</title>
      {values.map((v, i) => {
        const h = (v / max) * (height - 2)
        return <path key={i} d={barPath(i * bw, height - h, Math.max(0.5, bw - gap), h)} fill="var(--viz-series-1)" />
      })}
    </svg>
  )
}

/** 比例条（如缺失率）：同色系浅色轨道 + 实色填充。 */
export function RatioBar({ value, width = 64 }: { value: number; width?: number }) {
  return (
    <span className="inline-block h-1.5 overflow-hidden rounded-full bg-[var(--viz-track)] align-middle" style={{ width }}>
      <span className="block h-full rounded-full bg-[var(--viz-series-1)]" style={{ width: `${Math.min(100, value * 100)}%` }} />
    </span>
  )
}

/** 以 0 为中线的发散条：减少向左（红）、增加向右（蓝）；数字另外显示，不只靠颜色。 */
export function DeltaBar({ value, maxAbs, width = 96 }: { value: number; maxAbs: number; width?: number }) {
  const half = width / 2
  const len = maxAbs ? (Math.abs(value) / maxAbs) * (half - 1) : 0
  return (
    <svg width={width} height={10} aria-hidden>
      <line x1={half} x2={half} y1={0} y2={10} stroke="var(--viz-axis)" strokeWidth={1} />
      {value !== 0 && (
        <rect
          x={value < 0 ? half - len : half}
          y={2}
          width={Math.max(1, len)}
          height={6}
          rx={2}
          fill={value < 0 ? 'var(--viz-neg)' : 'var(--viz-pos)'}
        />
      )}
    </svg>
  )
}
