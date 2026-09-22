import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Lock, Trash2 } from 'lucide-react'
import { api } from '../../api'
import { fmtTime } from '../../lib/format'
import { inScope, useScope } from '../../lib/scope'
import type { Decision, Issue, PendingItem, Tracker, TrackerKind } from '../../types'

const TABS: [TrackerKind, string][] = [
  ['issues', '问题'],
  ['pending', '待决事项'],
  ['decisions', '决策日志'],
]
const input = 'w-full rounded border border-slate-300 px-2 py-1 text-sm outline-none focus:border-blue-500'
const lines = (s: string) => s.split('\n').map((x) => x.trim()).filter(Boolean)

/** 问题、待决事项、决策日志：在这里增改；项目文件里已有的待决事项只读显示并注明出处。只在总览有一份，步骤看板和阶段概况的「去处理」都跳到这里。 */
export default function TrackerPage() {
  const scope = useScope()
  const id = scope.pid
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as TrackerKind) || 'issues'
  const project = useQuery({ queryKey: ['project', id], queryFn: () => api.project(id) })
  const tracker = useQuery({ queryKey: ['tracker', id], queryFn: () => api.tracker(id) })
  const steps = (project.data?.graph?.nodes ?? []).filter((n) => inScope(scope, n.id)).map((n) => ({ id: n.id, title: n.title }))
  const raw = tracker.data
  const t: Tracker | undefined = raw && {
    ...raw,
    issues: raw.issues.filter((i) => inScope(scope, i.step)),
    decisions: raw.decisions.filter((i) => inScope(scope, i.step)),
    pending: raw.pending.filter((i) => inScope(scope, i.step)),
    project_pending: raw.project_pending.filter((i) => inScope(scope, i.step)),
  }
  const defaultStep = scope.stage ? (steps[0]?.id ?? '') : ''

  return (
    <div className="mx-auto max-w-5xl px-6 py-4">
      {t?.readonly && (
        <p className="mb-2 inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">
          <Lock className="h-3 w-3" aria-hidden />
          只读接入：这里新增的记录保存在平台目录，不写进项目文件。
        </p>
      )}
      <div role="tablist" className="mb-4 flex gap-1 border-b border-slate-200">
        {TABS.map(([k, label]) => {
          const n = !t ? 0 : k === 'issues' ? t.issues.filter((i) => i.status === 'open').length : k === 'pending' ? [...t.pending, ...t.project_pending].filter((p) => p.status !== 'resolved').length : t.decisions.length
          return (
            <button
              key={k}
              role="tab"
              aria-selected={tab === k}
              onClick={() => setParams({ tab: k })}
              className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${tab === k ? 'border-blue-600 font-medium text-blue-700' : 'border-transparent text-slate-600 hover:text-slate-900'}`}
            >
              {label}
              <span className="ml-1 text-xs text-slate-500">{n}</span>
            </button>
          )
        })}
      </div>
      {tracker.isLoading && <p className="text-sm text-slate-500">读取中…</p>}
      {tracker.error && <p className="text-sm text-red-600">{(tracker.error as Error).message}</p>}
      {t && tab === 'issues' && <Issues pid={id} items={t.issues} steps={steps} defaultStep={defaultStep} />}
      {t && tab === 'pending' && <Pending pid={id} t={t} steps={steps} defaultStep={defaultStep} />}
      {t && tab === 'decisions' && <Decisions pid={id} items={t.decisions} steps={steps} defaultStep={defaultStep} />}
    </div>
  )
}

type StepOpt = { id: string; title: string }

function useTracker(pid: string) {
  const qc = useQueryClient()
  const done = () => {
    qc.invalidateQueries({ queryKey: ['tracker', pid] })
    qc.invalidateQueries({ queryKey: ['board', pid] })
    qc.invalidateQueries({ queryKey: ['knowledge', pid] })
  }
  return {
    create: useMutation({ mutationFn: ({ kind, body }: { kind: TrackerKind; body: Record<string, unknown> }) => api.createItem(pid, kind, body), onSuccess: done }),
    update: useMutation({
      mutationFn: ({ kind, itemId, patch }: { kind: TrackerKind; itemId: string; patch: Record<string, unknown> }) => api.updateItem(pid, kind, itemId, patch),
      onSuccess: done,
    }),
    remove: useMutation({ mutationFn: ({ kind, itemId }: { kind: TrackerKind; itemId: string }) => api.deleteItem(pid, kind, itemId), onSuccess: done }),
  }
}

function StepSelect({ value, onChange, steps }: { value: string; onChange: (v: string) => void; steps: StepOpt[] }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="关联步骤" className="rounded border border-slate-300 bg-white px-1.5 py-1 text-sm">
      <option value="">不关联步骤</option>
      {steps.map((s) => (
        <option key={s.id} value={s.id}>
          {s.id} {s.title}
        </option>
      ))}
    </select>
  )
}

function AddForm({ title, onSubmit, pending, error, children }: { title: string; onSubmit: () => void; pending: boolean; error: unknown; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  if (!open)
    return (
      <button onClick={() => setOpen(true)} className="mb-3 rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700">
        {title}
      </button>
    )
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit()
  }
  return (
    <form onSubmit={submit} className="mb-4 space-y-2 rounded-lg border border-blue-200 bg-blue-50/40 p-3">
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
      <div className="flex items-center gap-2">
        <button type="submit" disabled={pending} className="rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          {pending ? '保存中…' : '保存'}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="text-sm text-slate-600 underline">
          取消
        </button>
        {error ? <span className="text-xs text-red-600">{(error as Error).message}</span> : null}
      </div>
    </form>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-xs text-slate-600">
      {label}
      <div className="mt-0.5">{children}</div>
    </label>
  )
}

function StepTag({ pid, step }: { pid: string; step?: string | null }) {
  if (!step) return null
  return (
    <Link to={`/p/${pid}/steps/${step}`} className="rounded bg-slate-100 px-1 text-[11px] text-blue-700 hover:underline">
      {step}
    </Link>
  )
}

function DeleteButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={() => {
        if (confirm('删除这条记录？删除后不可恢复。')) onClick()
      }}
      className="inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-xs text-slate-500 hover:bg-red-50 hover:text-red-700"
      aria-label="删除"
    >
      <Trash2 className="h-3.5 w-3.5" aria-hidden />
    </button>
  )
}

// ---------- 问题 ----------

function Issues({ pid, items, steps, defaultStep }: { pid: string; items: Issue[]; steps: StepOpt[]; defaultStep: string }) {
  const m = useTracker(pid)
  const empty = { title: '', step: defaultStep, severity: '中', blocking: false, note: '' }
  const [f, setF] = useState(empty)
  const [notes, setNotes] = useState<Record<string, string>>({})
  const open = items.filter((i) => i.status === 'open')
  const closed = items.filter((i) => i.status === 'resolved')
  return (
    <div>
      <AddForm
        title="记录问题"
        pending={m.create.isPending}
        error={m.create.error}
        onSubmit={() => m.create.mutate({ kind: 'issues', body: { ...f, step: f.step || null } }, { onSuccess: () => setF(empty) })}
      >
        <Field label="问题（发现了什么，用数据里的说法）">
          <input className={input} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required />
        </Field>
        <div className="flex flex-wrap items-center gap-3">
          <StepSelect value={f.step} onChange={(step) => setF({ ...f, step })} steps={steps} />
          <select value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })} aria-label="严重程度" className="rounded border border-slate-300 bg-white px-1.5 py-1 text-sm">
            {['高', '中', '低'].map((s) => (
              <option key={s} value={s}>
                严重程度：{s}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1 text-sm">
            <input type="checkbox" checked={f.blocking} onChange={(e) => setF({ ...f, blocking: e.target.checked })} />
            阻塞后续执行
          </label>
        </div>
        <Field label="备注（可选）">
          <textarea className={input} rows={2} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
        </Field>
      </AddForm>
      {!items.length && <p className="rounded-lg border border-dashed border-slate-300 p-4 text-sm leading-relaxed text-slate-600">还没有记录问题。执行中发现数据或结果有疑点，在这里记一条，标上严重程度和是否阻塞后续；解决后写明怎么解决的。</p>}
      <ul className="space-y-2">
        {open.map((i) => (
          <li key={i.id} className={`rounded-lg border bg-white p-3 ${i.blocking ? 'border-amber-300' : 'border-slate-200'}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-slate-500">{i.id}</span>
              <span className="font-medium">{i.title}</span>
              <span className="rounded bg-slate-100 px-1 text-[11px]">严重程度 {i.severity}</span>
              {i.blocking && <span className="rounded bg-amber-100 px-1 text-[11px] text-amber-900">阻塞后续执行</span>}
              <StepTag pid={pid} step={i.step} />
              <span className="ml-auto text-[11px] text-slate-500">{fmtTime(i.created_at)}</span>
            </div>
            {i.note && <p className="mt-1 text-sm text-slate-700">{i.note}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input
                className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-0.5 text-sm"
                placeholder="怎么解决的（写进备注）"
                value={notes[i.id] ?? ''}
                onChange={(e) => setNotes({ ...notes, [i.id]: e.target.value })}
              />
              <button
                onClick={() => m.update.mutate({ kind: 'issues', itemId: i.id, patch: { status: 'resolved', note: [i.note, notes[i.id]].filter(Boolean).join('\n') } })}
                className="rounded border border-green-300 bg-green-50 px-2 py-0.5 text-xs text-green-800 hover:bg-green-100"
              >
                标为已解决
              </button>
              <DeleteButton onClick={() => m.remove.mutate({ kind: 'issues', itemId: i.id })} />
            </div>
          </li>
        ))}
      </ul>
      {closed.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-slate-600">已解决（{closed.length}）</summary>
          <ul className="mt-2 space-y-1.5">
            {closed.map((i) => (
              <li key={i.id} className="rounded border border-slate-200 bg-white px-3 py-2 text-sm">
                <span className="font-mono text-xs text-slate-500">{i.id}</span> <span className="text-slate-600 line-through">{i.title}</span> <StepTag pid={pid} step={i.step} />
                <span className="ml-2 text-[11px] text-slate-500">解决于 {fmtTime(i.resolved_at)}</span>
                {i.note && <p className="mt-0.5 whitespace-pre-line text-[13px] text-slate-700">{i.note}</p>}
                <button onClick={() => m.update.mutate({ kind: 'issues', itemId: i.id, patch: { status: 'open' } })} className="mt-1 text-xs text-slate-600 underline">
                  重新打开
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

// ---------- 待决事项 ----------

function PendingCard({ it, pid, children }: { it: PendingItem; pid: string; children?: ReactNode }) {
  return (
    <li className={`rounded-lg border bg-white p-3 ${it.blocking && it.status !== 'resolved' ? 'border-amber-300' : 'border-slate-200'}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-slate-500">{it.id}</span>
        <span className="font-medium">{it.question}</span>
        {it.blocking && <span className="rounded bg-amber-100 px-1 text-[11px] text-amber-900">阻塞后续执行</span>}
        {it.status === 'resolved' && <span className="rounded bg-green-100 px-1 text-[11px] text-green-800">已裁定</span>}
        <StepTag pid={pid} step={it.step} />
      </div>
      <dl className="mt-1 grid grid-cols-[4.5rem_1fr] gap-x-2 gap-y-0.5 text-[13px] leading-relaxed">
        {(
          [
            ['推荐答案', it.recommendation],
            ['依据', it.basis],
            ['备选差异', it.alternatives],
            ['影响范围', it.impact],
          ] as const
        ).map(([k, v]) =>
          v ? (
            <div key={k} className="contents">
              <dt className="text-slate-500">{k}</dt>
              <dd>{v}</dd>
            </div>
          ) : null,
        )}
        {it.resolved_answer && (
          <>
            <dt className="text-slate-500">裁定</dt>
            <dd className="font-medium">{it.resolved_answer}</dd>
          </>
        )}
      </dl>
      {children}
    </li>
  )
}

function Pending({ pid, t, steps, defaultStep }: { pid: string; t: Tracker; steps: StepOpt[]; defaultStep: string }) {
  const m = useTracker(pid)
  const empty = { question: '', recommendation: '', basis: '', impact: '', step: defaultStep, blocking: false }
  const [f, setF] = useState(empty)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const sources = new Map<string, PendingItem[]>()
  for (const it of t.project_pending) sources.set(it.source!, [...(sources.get(it.source!) ?? []), it])
  return (
    <div>
      <AddForm
        title="记录待决事项"
        pending={m.create.isPending}
        error={m.create.error}
        onSubmit={() => m.create.mutate({ kind: 'pending', body: { ...f, step: f.step || null } }, { onSuccess: () => setF(empty) })}
      >
        <Field label="需要裁定的问题">
          <input className={input} value={f.question} onChange={(e) => setF({ ...f, question: e.target.value })} required />
        </Field>
        <Field label="推荐答案">
          <input className={input} value={f.recommendation} onChange={(e) => setF({ ...f, recommendation: e.target.value })} />
        </Field>
        <Field label="依据">
          <input className={input} value={f.basis} onChange={(e) => setF({ ...f, basis: e.target.value })} />
        </Field>
        <Field label="影响范围">
          <input className={input} value={f.impact} onChange={(e) => setF({ ...f, impact: e.target.value })} />
        </Field>
        <div className="flex flex-wrap items-center gap-3">
          <StepSelect value={f.step} onChange={(step) => setF({ ...f, step })} steps={steps} />
          <label className="flex items-center gap-1 text-sm">
            <input type="checkbox" checked={f.blocking} onChange={(e) => setF({ ...f, blocking: e.target.checked })} />
            阻塞后续执行
          </label>
        </div>
      </AddForm>

      {t.pending.length > 0 && (
        <ul className="mb-5 space-y-2">
          {t.pending.map((it) => (
            <PendingCard key={it.id} it={it} pid={pid}>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {it.status !== 'resolved' ? (
                  <>
                    <input
                      className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-0.5 text-sm"
                      placeholder={it.recommendation ? '裁定结果（留空则采用推荐答案）' : '裁定结果'}
                      value={answers[it.id] ?? ''}
                      onChange={(e) => setAnswers({ ...answers, [it.id]: e.target.value })}
                    />
                    <button
                      onClick={() => m.update.mutate({ kind: 'pending', itemId: it.id, patch: { status: 'resolved', resolved_answer: answers[it.id] || it.recommendation } })}
                      disabled={!answers[it.id] && !it.recommendation}
                      className="rounded border border-green-300 bg-green-50 px-2 py-0.5 text-xs text-green-800 hover:bg-green-100 disabled:opacity-50"
                    >
                      裁定
                    </button>
                  </>
                ) : (
                  <button onClick={() => m.update.mutate({ kind: 'pending', itemId: it.id, patch: { status: 'unresolved' } })} className="text-xs text-slate-600 underline">
                    撤回裁定
                  </button>
                )}
                <DeleteButton onClick={() => m.remove.mutate({ kind: 'pending', itemId: it.id })} />
              </div>
            </PendingCard>
          ))}
        </ul>
      )}

      {sources.size > 0 && (
        <section>
          <h2 className="mb-1 text-sm font-semibold">项目文件里的待决事项（只读）</h2>
          <p className="mb-2 text-sm text-slate-600">来自各步登记的待决事项，平台只读；裁定结果由执行 agent 写回项目文件。</p>
          {[...sources.entries()].map(([source, items]) => (
            <details key={source} className="mb-2 rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2" open={sources.size === 1}>
              <summary className="cursor-pointer text-sm">
                <b>{items[0].step}</b>（{items[0].revision}）· {items.length} 项，未裁定 {items.filter((i) => i.status !== 'resolved').length}，其中阻塞{' '}
                {items.filter((i) => i.blocking && i.status !== 'resolved').length}
                <span className="ml-2 break-all font-mono text-[11px] text-slate-500">{source}</span>
              </summary>
              <ul className="mt-2 space-y-2">
                {items.map((it) => (
                  <PendingCard key={it.id} it={it} pid={pid} />
                ))}
              </ul>
            </details>
          ))}
        </section>
      )}
      {!t.pending.length && !sources.size && <p className="rounded-lg border border-dashed border-slate-300 p-4 text-sm leading-relaxed text-slate-600">没有待决事项。执行 agent 拿不准、需要你拍板的问题会出现在这里，附推荐答案和依据；你裁定后它才能往下走。</p>}
    </div>
  )
}

// ---------- 决策日志 ----------

function Decisions({ pid, items, steps, defaultStep }: { pid: string; items: Decision[]; steps: StepOpt[]; defaultStep: string }) {
  const m = useTracker(pid)
  const empty = { title: '', context: '', decision: '', basis: '', rejected: '', impact: '', step: defaultStep }
  const [f, setF] = useState(empty)
  return (
    <div>
      <AddForm
        title="记录决策"
        pending={m.create.isPending}
        error={m.create.error}
        onSubmit={() =>
          m.create.mutate(
            { kind: 'decisions', body: { ...f, basis: lines(f.basis), rejected: lines(f.rejected), step: f.step || null } },
            { onSuccess: () => setF(empty) },
          )
        }
      >
        <Field label="标题">
          <input className={input} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required />
        </Field>
        <Field label="背景">
          <textarea className={input} rows={2} value={f.context} onChange={(e) => setF({ ...f, context: e.target.value })} />
        </Field>
        <Field label="决策">
          <textarea className={input} rows={2} value={f.decision} onChange={(e) => setF({ ...f, decision: e.target.value })} required />
        </Field>
        <Field label="依据（每行一条，可以写产物路径）">
          <textarea className={input} rows={2} value={f.basis} onChange={(e) => setF({ ...f, basis: e.target.value })} />
        </Field>
        <Field label="放弃的方案（每行一条，写明为什么放弃）">
          <textarea className={input} rows={2} value={f.rejected} onChange={(e) => setF({ ...f, rejected: e.target.value })} />
        </Field>
        <Field label="影响范围">
          <input className={input} value={f.impact} onChange={(e) => setF({ ...f, impact: e.target.value })} />
        </Field>
        <StepSelect value={f.step} onChange={(step) => setF({ ...f, step })} steps={steps} />
      </AddForm>
      {!items.length && <p className="rounded-lg border border-dashed border-slate-300 p-4 text-sm leading-relaxed text-slate-600">还没有记录决策。每做一个影响后续方向的选择（用哪个模型、删不删同值行），在这里记下决策、依据和放弃的方案，以后回头能看到为什么。</p>}
      <ol className="space-y-2">
        {[...items].reverse().map((d) => (
          <li key={d.id} className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-slate-500">{d.id}</span>
              <span className="font-medium">{d.title}</span>
              <StepTag pid={pid} step={d.step} />
              <span className="ml-auto text-[11px] text-slate-500">{d.date}</span>
              <DeleteButton onClick={() => m.remove.mutate({ kind: 'decisions', itemId: d.id })} />
            </div>
            <dl className="mt-1 grid grid-cols-[4.5rem_1fr] gap-x-2 gap-y-0.5 text-[13px] leading-relaxed">
              {d.context && (
                <>
                  <dt className="text-slate-500">背景</dt>
                  <dd>{d.context}</dd>
                </>
              )}
              <dt className="text-slate-500">决策</dt>
              <dd className="font-medium">{d.decision}</dd>
              {d.basis.length > 0 && (
                <>
                  <dt className="text-slate-500">依据</dt>
                  <dd>
                    <ul className="list-disc pl-4">
                      {d.basis.map((x, i) => (
                        <li key={i}>{x}</li>
                      ))}
                    </ul>
                  </dd>
                </>
              )}
              {d.rejected.length > 0 && (
                <>
                  <dt className="text-slate-500">放弃的方案</dt>
                  <dd>
                    <ul className="list-disc pl-4">
                      {d.rejected.map((x, i) => (
                        <li key={i}>{x}</li>
                      ))}
                    </ul>
                  </dd>
                </>
              )}
              {d.impact && (
                <>
                  <dt className="text-slate-500">影响范围</dt>
                  <dd>{d.impact}</dd>
                </>
              )}
            </dl>
          </li>
        ))}
      </ol>
    </div>
  )
}
