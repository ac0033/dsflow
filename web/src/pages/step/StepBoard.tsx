import { Link } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, CircleHelp, PauseCircle, RotateCcw, XCircle } from 'lucide-react'
import { api } from '../../api'
import AlertList from '../../components/AlertList'
import StatusBadge, { STATUS_COLOR } from '../../components/StatusBadge'
import { fmtNum, fmtTime } from '../../lib/format'
import { resolvePath } from '../../lib/paths'
import type { CoreNumber, Guide, NumberCheck, RevisionDetail, StepDetail } from '../../types'
import './board.css'

/** 说明卡文字里的 **加粗**。 */
function Inline({ text }: { text: string }) {
  const parts = text.split(/\*\*([^*\n]+)\*\*/)
  return <>{parts.map((p, i) => (i % 2 ? <strong key={i}>{p}</strong> : p))}</>
}

/**
 * 步骤看板（业务层）：一屏看清这一步的业务脉络与结果。
 * 讲解的开头与各段问题画成思维导图；核心数字优先用图（说明卡里的图、平台按数字画的条形图），画不出来才用指标卡片；
 * 再是分析结论 / 易错点、轮次、等你处理的事。产物图在执行层的「产物」。
 */
export default function StepBoard({ pid, root, d, rev, onTab }: {
  pid: string
  root?: string
  d: StepDetail
  rev: RevisionDetail
  onTab: (tab: 'guide' | 'products') => void
}) {
  const guide = useQuery({ queryKey: ['guide', pid, d.step.id, rev.id], queryFn: () => api.guide(pid, d.step.id, rev.id) })
  const board = useQuery({ queryKey: ['board', pid], queryFn: () => api.board(pid), refetchInterval: 20000 })
  const checks = useQuery({ queryKey: ['checks', pid, d.step.id], queryFn: () => api.stepChecks(pid, d.step.id), enabled: rev.is_current && !!rev.card })
  const g = guide.data?.guide ?? null
  const card = rev.card
  const can = g ? g.brief.can_continue : (card?.can_continue ?? null)
  const mine = <T extends { step?: string | null }>(xs: T[] | undefined) => (xs ?? []).filter((x) => x.step === d.step.id)
  const alerts = mine(board.data?.alerts)
  const pending = mine(board.data?.attention.blocking_decisions)
  const issues = mine(board.data?.attention.open_issues)
  const conclusions = card?.can_say ?? []
  const pitfalls = g?.cannot_say.length ? g.cannot_say : (card?.cannot_say ?? [])
  const figures = (card?.artifacts ?? []).filter((a) => a.kind === 'figure' || /\.(svg|png|jpe?g|webp)$/i.test(a.path))

  return (
    <div className="max-w-5xl space-y-4">
      {rev.card_error && <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">{rev.card_error}</p>}

      <section className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm">
        <StatusBadge status={d.step.status} />
        <Continue value={can} />
        <span className="text-slate-500">
          {rev.id}
          {rev.date ? ` · ${fmtTime(rev.date).slice(0, 10)}` : ''}
        </span>
        <button onClick={() => onTab('guide')} className="ml-auto text-blue-700 underline underline-offset-2">
          逐格讲解
        </button>
        <button onClick={() => onTab('products')} className="text-blue-700 underline underline-offset-2">
          产物
        </button>
      </section>

      {guide.isLoading ? <p className="text-sm text-slate-500">读取讲解…</p> : <MindMap title={`${d.step.id} ${d.step.title}`} g={g} d={d} rev={rev} />}

      {(figures.length > 0 || (card && card.core_numbers.length > 0)) && (
        <section className="space-y-3">
          {figures.length > 0 && (
            <div className="grid gap-3 md:grid-cols-2">
              {figures.map((f) => {
                const full = resolvePath(rev.dir, f.path, root) ?? f.path
                return (
                  <figure key={f.path} className="rounded-xl border border-slate-200 bg-white p-2">
                    <img src={`/api/projects/${pid}/file/raw?path=${encodeURIComponent(full)}`} alt={f.purpose} className="mx-auto max-h-80 w-full object-contain" />
                    <figcaption className="mt-1 text-center text-sm text-slate-600">{f.purpose}</figcaption>
                  </figure>
                )
              })}
            </div>
          )}
          {card && card.core_numbers.length > 0 && <Numbers numbers={card.core_numbers} checks={checks.data?.numbers?.items} />}
        </section>
      )}

      {(conclusions.length > 0 || pitfalls.length > 0) && (
        <div className="grid gap-3 sm:grid-cols-2">
          <section className="rounded-lg border border-slate-200 bg-white p-3">
            <h3 className="mb-1.5 text-sm font-semibold text-slate-700">分析结论</h3>
            {conclusions.length ? (
              <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
                {conclusions.map((x, i) => (
                  <li key={i}><Inline text={x} /></li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-400">说明卡没有写。</p>
            )}
          </section>
          <section className="rounded-lg border border-amber-300 bg-amber-50 p-3">
            <h3 className="mb-1.5 flex items-center gap-1 text-sm font-semibold text-amber-900">
              <AlertTriangle className="h-4 w-4" aria-hidden />
              易错点
            </h3>
            <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
              {pitfalls.map((x, i) => (
                <li key={i}><Inline text={x} /></li>
              ))}
            </ul>
          </section>
        </div>
      )}

      <Revisions d={d} current={rev} />

      {(alerts.length > 0 || pending.length > 0 || issues.length > 0) && (
        <section className="rounded-lg border border-amber-200 bg-amber-50/50 p-3">
          <h3 className="mb-1.5 text-sm font-semibold text-amber-900">这一步等你处理的事</h3>
          {alerts.length > 0 && <AlertList pid={pid} alerts={alerts} />}
          {(pending.length > 0 || issues.length > 0) && (
            <ul className="mt-1.5 space-y-1 text-sm">
              {issues.map((i) => (
                <li key={i.id}>
                  <span className="font-mono text-xs text-slate-500">{i.id}</span> {i.title}
                  <span className="ml-1 text-xs text-slate-500">{i.severity}{i.blocking ? ' · 阻塞' : ''}</span>
                </li>
              ))}
              {pending.map((p) => (
                <li key={`${p.source ?? 'p'}-${p.id}`}>
                  <span className="font-mono text-xs text-slate-500">{p.id}</span> {p.question}
                  <span className="ml-1 text-xs text-amber-800">阻塞</span>
                </li>
              ))}
              <li>
                <Link to={`/p/${pid}/tracker`} className="text-sm text-blue-700 underline">去处理</Link>
              </li>
            </ul>
          )}
        </section>
      )}
    </div>
  )
}

function Continue({ value }: { value: boolean | null }) {
  const [Icon, text, cls] =
    value === true
      ? [CheckCircle2, '可以继续', 'bg-green-100 text-green-800']
      : value === false
        ? [PauseCircle, '暂不能继续', 'bg-amber-100 text-amber-900']
        : [CircleHelp, '未说明能否继续', 'bg-slate-100 text-slate-600']
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {text}
    </span>
  )
}

/* ---------- 思维导图：讲解的开头五段 + 每个问题的答案与业务含义 ---------- */

type Branch = { label: string; text: string; tone: 'bg' | 'q' | 'a' | 'op' | 'next' | 'part'; strong?: boolean; children?: { label: string; text: string }[] }

function branchesOf(g: Guide | null, d: StepDetail, rev: RevisionDetail): Branch[] {
  if (g) {
    const b = g.brief
    const out: Branch[] = ([
      { label: '背景', text: b.background, tone: 'bg' },
      { label: '目的', text: b.question, tone: 'q' },
      { label: '结论', text: b.answer, tone: 'a', strong: true },
      { label: '操作', text: b.did, tone: 'op' },
      { label: '结果', text: b.result, tone: 'op' },
      { label: '下一步', text: b.next, tone: 'next' },
    ] as Branch[]).filter((x) => x.text)
    g.parts.forEach((p, i) => {
      const children = [
        p.answer ? { label: '答案', text: p.answer } : null,
        p.meaning ? { label: '业务含义', text: p.meaning } : null,
        p.cells.length ? { label: '过程', text: p.cells.map((c) => c.title).filter(Boolean).join(' → ') } : null,
      ].filter((x): x is { label: string; text: string } => !!x && !!x.text)
      out.push({ label: `问题 ${i + 1}`, text: p.question, tone: 'part', children })
    })
    return out
  }
  const card = rev.card
  return ([
    { label: '目的', text: d.step.op, tone: 'q' },
    { label: '结论', text: card?.headline || d.step.finding, tone: 'a', strong: true },
    { label: '操作', text: card?.operation ?? '', tone: 'op' },
    { label: '决策', text: d.step.decision, tone: 'next' },
  ] as Branch[]).filter((x) => x.text)
}

function MindMap({ title, g, d, rev }: { title: string; g: Guide | null; d: StepDetail; rev: RevisionDetail }) {
  const branches = branchesOf(g, d, rev)
  if (!branches.length) return <p className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-600">这一步暂未讲解，也还没有登记结论。</p>
  return (
    <section className="mm-wrap">
      {!g && <p className="mb-2 text-xs text-amber-800">暂未讲解，下面是这一步登记的目的与结论。</p>}
      <div className="mm">
        <div className="mm-root">{title}</div>
        <ul className="mm-branches">
          {branches.map((b, i) => (
            <li key={i}>
              <div className={`mm-node tone-${b.tone}${b.strong ? ' strong' : ''}`}>
                <span className="lbl">{b.label}</span>
                <span className="txt">{b.text}</span>
              </div>
              {b.children && b.children.length > 0 && (
                <ul className="mm-branches mm-children">
                  {b.children.map((c, j) => (
                    <li key={j}>
                      <div className="mm-node leaf">
                        <span className="lbl">{c.label}</span>
                        <span className="txt">{c.text}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

/* ---------- 核心数字：能画就画（同一单位、两个以上数值），画不了用指标卡片 ---------- */

const num = (v: CoreNumber['after']): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v)) ? Number(v) : null)

function CheckMark({ n }: { n?: NumberCheck }) {
  if (!n || n.status === 'no_source') return null
  if (n.status === 'match') return <CheckCircle2 className="h-3.5 w-3.5 text-green-700" aria-label="已核对" />
  if (n.status === 'mismatch') return <XCircle className="h-3.5 w-3.5 text-red-700" aria-label={`产物里是 ${fmtNum(n.actual, 6)}`} />
  return <AlertTriangle className="h-3.5 w-3.5 text-amber-700" aria-label="无法核对" />
}

function Numbers({ numbers, checks }: { numbers: CoreNumber[]; checks?: NumberCheck[] }) {
  const values = numbers.map((n) => num(n.after))
  const befores = numbers.map((n) => num(n.before))
  const units = new Set(numbers.map((n) => n.unit || ''))
  const chartable = numbers.length >= 2 && values.every((v) => v != null) && units.size === 1
  if (!chartable) {
    return (
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {numbers.map((n, i) => (
          <div key={i} className="rounded-lg border border-slate-200 bg-white p-3">
            <p className="flex items-center gap-1 text-xs text-slate-500">
              {n.label}
              {n.unit && <span>（{n.unit}）</span>}
              <CheckMark n={checks?.[i]} />
            </p>
            <p className="tabular text-xl font-semibold leading-tight text-slate-900">{n.after == null || n.after === '' ? '—' : typeof n.after === 'number' ? fmtNum(n.after, 4) : n.after}</p>
            {n.before != null && n.before !== '' && <p className="tabular mt-0.5 text-xs text-slate-500">处理前 {typeof n.before === 'number' ? fmtNum(n.before, 4) : n.before}</p>}
            {n.scope && <p className="mt-1 text-xs leading-relaxed text-slate-500">{n.scope}</p>}
          </div>
        ))}
      </div>
    )
  }
  const hasBefore = befores.some((v) => v != null)
  const maxAbs = Math.max(...values.map((v) => Math.abs(v!)), ...befores.map((v) => (v == null ? 0 : Math.abs(v)))) || 1
  const unit = [...units][0]
  return (
    <figure className="rounded-xl border border-slate-200 bg-white p-3">
      <ul className="space-y-2">
        {numbers.map((n, i) => {
          const v = values[i]!
          const b = befores[i]
          return (
            <li key={i} className="grid grid-cols-[minmax(0,22rem)_1fr_auto] items-center gap-3 text-sm">
              <span className="flex items-center gap-1 leading-tight text-slate-700" title={n.scope}>
                {n.label}
                <CheckMark n={checks?.[i]} />
              </span>
              <span className="relative h-6">
                {hasBefore && b != null && <Bar value={b} maxAbs={maxAbs} cls="bar before" />}
                <Bar value={v} maxAbs={maxAbs} cls="bar after" />
              </span>
              <span className="tabular w-32 text-right font-semibold text-slate-900">
                {hasBefore && b != null && <span className="mr-1 text-xs font-normal text-slate-400">{fmtNum(b, 4)} →</span>}
                {fmtNum(v, 4)}
                {unit && <span className="ml-0.5 text-xs font-normal text-slate-500">{unit}</span>}
              </span>
            </li>
          )
        })}
      </ul>
      {(hasBefore || values.some((v) => v! < 0)) && (
        <figcaption className="mt-2 text-xs text-slate-500">
          {[hasBefore ? '浅色是处理前，深色是处理后' : '', values.some((v) => v! < 0) ? '负值向左' : ''].filter(Boolean).join('；')}。
        </figcaption>
      )}
    </figure>
  )
}

function Bar({ value, maxAbs, cls }: { value: number; maxAbs: number; cls: string }) {
  const hasNeg = value < 0
  const w = (Math.abs(value) / maxAbs) * 50
  return <span className={cls} style={hasNeg ? { right: '50%', width: `${w}%` } : { left: '50%', width: `${w}%` }} />
}

/** 轮次：每一轮相对上一轮递进了什么、为什么返工。 */
function Revisions({ d, current }: { d: StepDetail; current: RevisionDetail }) {
  if (d.revisions.length <= 1) return null
  const loopTo = new Map(d.revision_loops.map((l) => [l.to_revision, l]))
  return (
    <section>
      <h3 className="mb-1.5 text-sm font-semibold text-slate-700">轮次</h3>
      <ol className="space-y-1">
        {d.revisions.map((r, i) => {
          const loop = loopTo.get(r.id)
          return (
            <li key={r.id} className={`flex flex-wrap items-baseline gap-2 rounded-lg border bg-white px-3 py-1.5 text-sm ${r.id === current.id ? 'border-blue-300' : 'border-slate-200'}`}>
              <span className="inline-flex items-center gap-1 font-mono text-xs">
                <span className="h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[r.status] }} aria-hidden />
                {r.id}
              </span>
              <span className="text-xs text-slate-500">{r.status_label}{r.date ? ` · ${r.date}` : ''}</span>
              {i > 0 && loop && (
                <span className="inline-flex items-center gap-1 text-xs text-red-700">
                  <RotateCcw className="h-3 w-3" aria-hidden />
                  {loop.from_revision} → {loop.to_revision}：{loop.label || '未写原因'}
                </span>
              )}
              <span className="min-w-0 flex-1 text-slate-700">
                {r.summary || (i > 0 ? <span className="text-amber-800">没有写相对 {d.revisions[i - 1].id} 递进了什么</span> : <span className="text-slate-400">第一轮</span>)}
              </span>
              {r.is_current && <span className="text-xs text-slate-500">当前</span>}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
