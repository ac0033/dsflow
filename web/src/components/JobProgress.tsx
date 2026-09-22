import type { Job } from '../types'

/** 后台任务进度：有进度数字时显示比例条，没有时显示来回滑动的条。 */
export default function JobProgress({ job }: { job: Job<unknown> | null }) {
  if (!job) return null
  if (job.status === 'failed') {
    return <p className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700">失败：{job.error}</p>
  }
  if (job.status === 'succeeded') return null
  const pct = job.progress == null ? null : Math.round(job.progress * 100)
  return (
    <div className="space-y-1" role="status" aria-live="polite">
      <div className="h-1.5 overflow-hidden rounded bg-[var(--viz-track)]">
        {pct == null ? (
          <div className="h-full w-2/5 animate-[indeterminate_1.2s_ease-in-out_infinite] bg-[var(--viz-series-1)]" />
        ) : (
          <div className="h-full bg-[var(--viz-series-1)] transition-[width]" style={{ width: `${pct}%` }} />
        )}
      </div>
      <p className="text-[11px] text-slate-500">
        {job.message}
        {pct != null ? ` · ${pct}%` : ''}
      </p>
    </div>
  )
}
