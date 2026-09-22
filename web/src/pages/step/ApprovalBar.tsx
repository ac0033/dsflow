import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ChevronDown, ChevronRight, RotateCcw, Undo2 } from 'lucide-react'
import { api, ApiError } from '../../api'
import type { ApprovalEntry, ApprovalView, StepDetail } from '../../types'

/**
 * 步骤页头的审批条，放在标题下面、选项卡上面——表态在这里做，改主意也在这里改。
 *
 * 「待审批」「待验收」时是完整的审批条：点「通过 / 确认完成 / 退回」→ 平台写审批记录并改步骤状态；
 * 其余时候只要这一轮有过审批，就留一条细条显示最近那次表态，点错了可以当场撤回。
 * 撤回不删记录：状态改回表态之前，审批记录里再追加一条「撤回」。
 */
export default function ApprovalBar({ pid, d, revId, readonly, onTab }: {
  pid: string
  d: StepDetail
  revId: string
  readonly?: boolean
  onTab: (tab: 'plan' | 'products') => void
}) {
  const qc = useQueryClient()
  const status = d.step.status
  const kind = status === 'pending_approval' ? 'approval' : status === 'awaiting_acceptance' ? 'acceptance' : null
  const view = useQuery({ queryKey: ['approval', pid, d.step.id, revId], queryFn: () => api.approvals(pid, d.step.id, revId) })
  const [note, setNote] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['step', pid, d.step.id] })
    qc.invalidateQueries({ queryKey: ['project', pid] })
    qc.invalidateQueries({ queryKey: ['board', pid] })
    qc.invalidateQueries({ queryKey: ['approval', pid, d.step.id] })
  }
  const decide = useMutation({
    mutationFn: (decision: 'approve' | 'reject') => api.decide(pid, d.step.id, { kind: kind!, decision, note, rev: revId }),
    onSuccess: (r) => {
      setNote('')
      setMessage(r.warnings.length ? r.warnings.join('；') : `已记入 ${r.record}，状态 ${r.from} → ${r.to}。`)
      refresh()
    },
    onError: (e) => setMessage(e instanceof ApiError ? e.message : String(e)),
  })
  const rev = d.revisions.find((r) => r.id === revId)
  const last: ApprovalEntry | undefined = view.data?.entries.at(-1)
  const undo = (
    <Withdraw pid={pid} stepId={d.step.id} revId={revId} view={view.data} onDone={(text) => { setMessage(text); refresh() }} />
  )

  if (kind == null) {
    if (!last) return null
    return (
      <section className="mb-3 rounded-lg border border-slate-200 bg-white px-3 py-2" aria-label="审批记录">
        <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
          <div className="min-w-[240px] flex-1">
            <LastEntry last={last} />
          </div>
          {undo}
        </div>
        {message && <p className="mt-1.5 text-xs text-slate-700">{message}</p>}
      </section>
    )
  }

  const hasAcceptance = (rev?.acceptance_reports.length ?? 0) > 0
  const hasPlan = rev?.files.some((f) => f.kind === 'plan' || f.kind === 'plan_user') ?? false
  const headline = kind === 'approval'
    ? (hasPlan ? '这一步的计划等你审批。' : '这一步等你审批，但还没有提交计划。')
    : (hasAcceptance ? '验收报告已写好，等你确认这一步完成。' : '这一步等你确认完成，但还没有写验收报告。')
  const approveLabel = kind === 'approval' ? '通过' : '确认完成'
  const rejectLabel = kind === 'approval' ? '退回' : '退回调整'
  const tone = kind === 'approval' ? 'border-orange-300 bg-orange-50' : 'border-sky-300 bg-sky-50'
  const busy = decide.isPending || readonly

  return (
    <section className={`mb-3 rounded-lg border px-4 py-3 text-sm ${tone}`} aria-label="审批">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium">{headline}</span>
        <button onClick={() => onTab(kind === 'approval' ? 'plan' : 'products')} className="text-blue-700 hover:underline">
          {kind === 'approval' ? '看计划' : '看验收报告与产物'}
        </button>
      </div>
      {last && (
        <div className="mt-1.5 flex flex-wrap items-start gap-x-3 gap-y-1">
          <div className="min-w-[240px] flex-1">
            <LastEntry last={last} />
          </div>
          {undo}
        </div>
      )}
      {readonly ? (
        <p className="mt-2 text-xs text-slate-600">只读接入的项目不能在平台审批。在对话里告诉 agent 你的决定，由它运行 <code>dsflow approve</code> 记录。</p>
      ) : (
        <div className="mt-2 flex flex-wrap items-start gap-2">
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="你的意见（会原样记下来，主 agent 据此继续）"
            aria-label="审批意见"
            className="min-w-[280px] flex-1 rounded border border-slate-300 bg-white px-2 py-1 text-sm"
          />
          <button
            disabled={busy || (kind === 'approval' && !hasPlan)}
            onClick={() => decide.mutate('approve')}
            className="inline-flex items-center gap-1 rounded bg-green-600 px-3 py-1.5 text-white hover:bg-green-700 disabled:opacity-50"
          >
            <CheckCircle2 className="h-4 w-4" aria-hidden />
            {approveLabel}
          </button>
          <button
            disabled={busy}
            onClick={() => decide.mutate('reject')}
            className="inline-flex items-center gap-1 rounded border border-slate-400 bg-white px-3 py-1.5 hover:bg-slate-50 disabled:opacity-50"
          >
            <RotateCcw className="h-4 w-4" aria-hidden />
            {rejectLabel}
          </button>
        </div>
      )}
      {message && <p className="mt-2 text-xs text-slate-700">{message}</p>}
    </section>
  )
}

/** 撤回最近一条审批：点一下先问「为什么撤回」，确认后状态改回去，记录里追加一条「撤回」。 */
function Withdraw({ pid, stepId, revId, view, onDone }: {
  pid: string
  stepId: string
  revId: string
  view?: ApprovalView
  onDone: (message: string) => void
}) {
  const [asking, setAsking] = useState(false)
  const [why, setWhy] = useState('')
  const run = useMutation({
    mutationFn: () => api.withdraw(pid, stepId, { note: why, rev: revId }),
    onSuccess: (r) => {
      setAsking(false)
      setWhy('')
      const w = r.withdrew
      onDone(`已撤回${w ? ` ${w.time} 的「${w.decision_label} · ${w.kind_label}」` : '上一条审批'}，状态 ${r.from} → ${r.to}；审批记录里留有这次撤回。`)
    },
    onError: (e) => onDone(e instanceof ApiError ? e.message : String(e)),
  })
  if (!view?.entries.length) return null
  if (!view.can_withdraw) {
    return (
      <span className="shrink-0 text-[11px] text-slate-400" title={view.withdraw_blocked}>
        不能撤回
      </span>
    )
  }
  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        className="inline-flex shrink-0 items-center gap-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50"
        title="填错了可以撤回：状态改回表态之前，审批记录里追加一条「撤回」"
      >
        <Undo2 className="h-3.5 w-3.5" aria-hidden />
        撤回这条
      </button>
    )
  }
  return (
    <div className="flex w-full flex-wrap items-center gap-2 rounded border border-slate-300 bg-white px-2 py-1.5">
      <span className="text-xs text-slate-600">撤回这一条，状态改回表态之前；记录不会删，会多一条「撤回」。</span>
      <input
        value={why}
        onChange={(e) => setWhy(e.target.value)}
        placeholder="为什么撤回（会原样记下来）"
        aria-label="撤回原因"
        className="min-w-[200px] flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
      />
      <button
        type="button"
        disabled={run.isPending}
        onClick={() => run.mutate()}
        className="rounded bg-amber-600 px-2.5 py-1 text-xs text-white hover:bg-amber-700 disabled:opacity-50"
      >
        {run.isPending ? '撤回中…' : '确认撤回'}
      </button>
      <button type="button" onClick={() => setAsking(false)} className="text-xs text-slate-500 hover:text-slate-800">
        取消
      </button>
    </div>
  )
}

/** 上一条审批记录：平时只占一行（时间 + 结论 + 意见的开头），点一下展开看原话。 */
function LastEntry({ last }: { last: ApprovalEntry }) {
  const [open, setOpen] = useState(false)
  const when = last.time.replace(/^\d{4}-/, '').slice(0, 11)
  const tone = last.decision === 'approve' ? 'bg-green-100 text-green-800'
    : last.decision === 'withdraw' ? 'bg-slate-200 text-slate-700' : 'bg-amber-100 text-amber-900'
  return (
    <div className="text-xs">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        disabled={!last.note}
        className="flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left text-slate-600 hover:bg-white/70 disabled:hover:bg-transparent"
        title={last.note || '这一条没有写意见'}
      >
        <span className="shrink-0 text-slate-400">上一条</span>
        <span className={`shrink-0 rounded px-1.5 ${tone}`}>{last.decision_label}</span>
        <span className="tabular shrink-0 text-slate-400">{last.kind_label} · {when}</span>
        {last.note ? (
          <span className="min-w-0 flex-1 truncate text-slate-700">「{last.note}」</span>
        ) : (
          <span className="min-w-0 flex-1 text-slate-400">没有写意见</span>
        )}
        {last.note &&
          (open ? <ChevronDown className="h-3 w-3 shrink-0 text-slate-400" aria-hidden /> : <ChevronRight className="h-3 w-3 shrink-0 text-slate-400" aria-hidden />)}
      </button>
      {open && last.note && (
        <p className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded border border-slate-200 bg-white px-2.5 py-1.5 leading-relaxed text-slate-700">
          {last.note}
        </p>
      )}
    </div>
  )
}
