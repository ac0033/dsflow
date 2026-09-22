import type { RunStatus, Validity } from '../types'

const STATUS: Record<RunStatus, [string, string]> = {
  running: ['运行中', 'bg-sky-100 text-sky-800'],
  succeeded: ['成功', 'bg-green-100 text-green-700'],
  failed: ['失败', 'bg-red-100 text-red-700'],
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const [label, cls] = STATUS[status]
  return <span className={`inline-block rounded px-1.5 py-px text-[11px] font-medium ${cls}`}>{label}</span>
}

const VALIDITY: Record<Validity, string> = {
  有效: 'border-green-300 text-green-800',
  无效: 'border-slate-300 text-slate-600',
  无结论: 'border-amber-300 text-amber-800',
}

/** 这次尝试的有效性：有效 / 无效 / 无结论（无效和无结论同样值得记录） */
export function ValidityBadge({ validity }: { validity?: Validity | null }) {
  if (!validity) return <span className="text-[11px] text-slate-400">未判断</span>
  return <span className={`inline-block rounded border px-1.5 text-[11px] ${VALIDITY[validity]}`}>{validity}</span>
}
