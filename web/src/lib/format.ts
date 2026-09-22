import type { Cell } from '../types'

const nf = new Intl.NumberFormat('zh-CN')

export const fmtInt = (n: number | null | undefined) => (n == null ? '—' : nf.format(n))

export function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n == null) return '—'
  const a = Math.abs(n)
  if (a !== 0 && (a >= 1e12 || a < 1e-3)) return n.toExponential(2)
  return n.toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

export const fmtPct = (x: number | null | undefined, digits = 1) => (x == null ? '—' : `${(x * 100).toFixed(digits)}%`)

export function fmtSigned(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n === 0) return '±0'
  return (n > 0 ? '+' : '−') + nf.format(Math.abs(n))
}

export function fmtSignedPct(x: number | null | undefined, digits = 1): string {
  if (x == null) return '—'
  if (x === 0) return '±0%'
  return (x > 0 ? '+' : '−') + `${Math.abs(x * 100).toFixed(digits)}%`
}

export function fmtDuration(s: number | null | undefined): string {
  if (s == null) return '—'
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} 秒`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} 分 ${Math.round(s % 60)} 秒`
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`
}

export const fmtTime = (iso: string | null | undefined) => (iso ? iso.replace('T', ' ').slice(0, 19) : '—')

export function fmtDelta(v: number, digits = 4): string {
  if (v === 0) return '±0'
  return (v > 0 ? '+' : '−') + fmtNum(Math.abs(v), digits)
}

export function fmtBytes(b: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = b
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

/** 大数用"万 / 亿"压缩，便于图表坐标轴。 */
export function fmtCompact(n: number): string {
  const a = Math.abs(n)
  if (a >= 1e8) return `${(n / 1e8).toFixed(a >= 1e9 ? 0 : 1)}亿`
  if (a >= 1e4) return `${(n / 1e4).toFixed(a >= 1e5 ? 0 : 1)}万`
  return fmtNum(n, a < 10 ? 2 : 0)
}

export function fmtCell(v: Cell): string {
  if (v === null) return ''
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : fmtNum(v, 6)
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  return v
}
