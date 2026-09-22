import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, CircleHelp, Gavel, GitCommitHorizontal, Play, RotateCcw, ShieldCheck } from 'lucide-react'
import { api } from '../../api'
import AlertList from '../../components/AlertList'
import StatusBadge, { STATUS_LABEL } from '../../components/StatusBadge'
import { fmtTime } from '../../lib/format'
import type { ActivityEvent, Board, Graph, PendingItem, StepBrief, StepStatus } from '../../types'

const ORDER: StepStatus[] = ['done', 'awaiting_acceptance', 'in_progress', 'partial', 'pending_approval', 'stopped', 'pending']

/** 看板：先说要不要你处理，再给告警、需要关注的步骤与事项、推进说明、迭代情况和最近动态。阶段进度在总览顶部的生命周期条。 */
export default function BoardPage() {
  const { id = '' } = useParams()
  const board = useQuery({ queryKey: ['board', id], queryFn: () => api.board(id), refetchInterval: 20000 })
  const project = useQuery({ queryKey: ['project', id], queryFn: () => api.project(id) })
  return (
    <div className="mx-auto max-w-6xl px-6 py-4">
      {board.isLoading && <p className="text-sm text-slate-500">汇总项目状态…</p>}
      {board.error && <p className="text-sm text-red-600">{(board.error as Error).message}</p>}
      {board.data && <BoardView pid={id} b={board.data} graph={project.data?.graph ?? null} />}
    </div>
  )
}

function BoardView({ pid, b, graph }: { pid: string; b: Board; graph: Graph | null }) {
  const a = b.attention
  const critical = b.alerts.filter((x) => x.level === 'critical').length
  const blockingIssues = a.open_issues.filter((i) => i.blocking).length
  const todo: [string, number][] = [
    ['待审批', a.pending_approval.length],
    ['待验收', a.awaiting_acceptance.length],
    ['阻塞后续的待决事项', a.blocking_decisions.length],
    ['阻塞的问题', blockingIssues],
  ]
  const need = todo.filter(([, n]) => n > 0)
  const counts = ORDER.filter((s) => b.status_counts[s]).map((s) => `${STATUS_LABEL[s]} ${b.status_counts[s]}`)
  const tc = b.tracker_counts
  const tracker = (
    [
      ['未解决的问题', tc.open_issues, '个'],
      ['未裁定的待决事项', tc.unresolved_pending, '项'],
      ['已记录决策', tc.decisions, '条'],
    ] as [string, number, string][]
  ).filter(([, n]) => n > 0)
  const mc = b.model_counts ?? {}
  const models = (
    [
      ['已交付', mc.delivered],
      ['已验收', mc.accepted],
      ['候选', mc.candidate],
    ] as [string, number | undefined][]
  ).filter(([, n]) => n)

  return (
    <div className="space-y-5">
      <section className={`rounded-lg border p-4 ${critical ? 'border-red-300 bg-red-50' : need.length ? 'border-amber-200 bg-amber-50/60' : 'border-green-200 bg-green-50/60'}`}>
        <p className="text-base font-semibold leading-relaxed">
          {critical > 0
            ? `有 ${critical} 条严重告警（原始数据可能被改），先处理再继续。`
            : need.length
              ? `需要你处理：${need.map(([k, n]) => `${k} ${n} 项`).join('、')}。`
              : '目前没有等你审批、验收或裁定的事项。'}
        </p>
        <p className="mt-1 text-sm text-slate-700">
          共 {b.total_steps} 步：{counts.join('、')}。
          {tracker.length > 0 && (
            <>
              {tracker.map(([k, n, u]) => `${k} ${n} ${u}`).join('，')}
              <Link to={`/p/${pid}/tracker`} className="ml-1 text-blue-700 underline">
                去处理
              </Link>
              。
            </>
          )}
          {models.length > 0 && (
            <>
              模型版本：{models.map(([k, n]) => `${k} ${n}`).join('、')}
              <Link to={`/p/${pid}/models`} className="ml-1 text-blue-700 underline">
                看模型
              </Link>
              。
            </>
          )}
        </p>
      </section>

      <Alerts pid={pid} b={b} />

      <Attention pid={pid} b={b} />

      {b.notes && graph && (
        <Block title="推进说明">
          <Notes pid={pid} text={b.notes} graph={graph} />
        </Block>
      )}

      <Iterations pid={pid} b={b} />

      <Block title="最近动态">
        <Activity pid={pid} events={b.activity} />
      </Block>
    </div>
  )
}

export function Block({ title, note, extra, children }: { title: string; note?: string; extra?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        {note && <span className="text-xs text-slate-500">{note}</span>}
        <span className="ml-auto">{extra}</span>
      </div>
      {children}
    </section>
  )
}

/** 严重 / 重要 / 注意的告警直接列出来；「提示」级别默认收起，免得把要处理的事淹没。 */
function Alerts({ pid, b }: { pid: string; b: Board }) {
  const major = b.alerts.filter((x) => x.level !== 'info')
  const infos = b.alerts.filter((x) => x.level === 'info')
  return (
    <Block title={`告警（${major.length}）`} extra={<VerifyButton pid={pid} show={b.alerts.some((x) => x.code === 'raw_maybe_changed')} />}>
      {major.length ? (
        <AlertList pid={pid} alerts={major} />
      ) : (
        <p className="inline-flex items-center gap-1 text-sm text-green-800">
          <CheckCircle2 className="h-4 w-4" aria-hidden />
          没有需要处理的告警。
        </p>
      )}
      {infos.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-sm text-slate-600">提示 {infos.length} 条</summary>
          <div className="mt-1.5">
            <AlertList pid={pid} alerts={infos} />
          </div>
        </details>
      )}
    </Block>
  )
}

function VerifyButton({ pid, show }: { pid: string; show: boolean }) {
  const qc = useQueryClient()
  const verify = useMutation({
    mutationFn: () => api.verifyRaw(pid),
    onSuccess: (alerts) => qc.setQueryData(['board', pid], (old: Board | undefined) => (old ? { ...old, alerts } : old)),
  })
  if (!show && !verify.isSuccess) return null
  return (
    <button
      onClick={() => verify.mutate()}
      disabled={verify.isPending}
      className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-50"
      title="大小或修改时间变了的原始数据，重新计算 SHA256 确认内容是否真的变了"
    >
      <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
      {verify.isPending ? '计算哈希中…' : verify.isSuccess ? '已按哈希核对' : '核对哈希'}
    </button>
  )
}

/* ---------- 推进说明：注册表 notes 里的一段话，拆成条目；提到的阶段、步骤变成可点的标签 ---------- */

const CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'

function Notes({ pid, text, graph }: { pid: string; text: string; graph: Graph }) {
  const items = text
    .split(/(?<=[。；;])\s*/)
    .map((s) => s.trim())
    .filter(Boolean)
  const stepIds = new Set(graph.nodes.map((n) => n.id))
  const stageByNo = new Map(graph.stages.map((s, i) => [CIRCLED[i], s]))
  const render = (s: string) => {
    const out: ReactNode[] = []
    const re = /([①-⑳])\s*|(\d+\.\d+)/g
    let last = 0
    let m: RegExpExecArray | null
    let k = 0
    while ((m = re.exec(s))) {
      if (m[1]) {
        const stage = stageByNo.get(m[1])
        if (!stage) continue
        out.push(s.slice(last, m.index))
        // 注册表里的阶段名自带序号（「④ 特征工程」），原文里序号后面跟的是不带序号的名字，一并吃掉
        const bare = stage.name.replace(/^[①-⑳]\s*/, '')
        let end = m.index + m[0].length
        if (s.startsWith(bare, end)) end += bare.length
        else if (s.startsWith(stage.name, end)) end += stage.name.length
        out.push(
          <Link
            key={k++}
            to={`/p/${pid}/stage/${stage.id}`}
            className="mx-0.5 inline-flex items-center gap-1 rounded-full border px-2 py-px align-baseline text-[13px] font-medium leading-5 hover:underline"
            style={{ borderColor: stage.color, color: stage.color, background: `${stage.color}12` }}
          >
            {stage.name}
          </Link>,
        )
        last = end
        re.lastIndex = end
      } else if (m[2] && stepIds.has(m[2])) {
        out.push(s.slice(last, m.index))
        out.push(
          <Link key={k++} to={`/p/${pid}/steps/${m[2]}`} className="font-medium text-blue-700 hover:underline">
            {m[2]}
          </Link>,
        )
        last = m.index + m[0].length
      }
    }
    out.push(s.slice(last))
    return out
  }
  return (
    <ul className="space-y-1.5">
      {items.map((s, i) => (
        <li key={i} className="flex items-start gap-2 text-sm leading-7">
          <span className="mt-3 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-400" aria-hidden />
          <span className="min-w-0">{render(s)}</span>
        </li>
      ))}
    </ul>
  )
}

function StepLinks({ pid, items, tab }: { pid: string; items: StepBrief[]; tab?: string }) {
  return (
    <ul className="space-y-1.5 text-sm">
      {items.map((s) => (
        <li key={s.step} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <Link to={`/p/${pid}/steps/${s.step}${tab ? `?tab=${tab}` : ''}`} className="font-medium text-blue-700 hover:underline">
            {s.step} {s.title}
          </Link>
          <StatusBadge status={s.status} />
          {s.summary && <span className="basis-full text-[13px] leading-relaxed text-slate-600">{s.summary}</span>}
        </li>
      ))}
    </ul>
  )
}

function groupPending(items: PendingItem[]) {
  const groups = new Map<string, PendingItem[]>()
  for (const it of items) {
    const key = it.source ?? '平台记录'
    groups.set(key, [...(groups.get(key) ?? []), it])
  }
  return [...groups.entries()]
}

function Attention({ pid, b }: { pid: string; b: Board }) {
  const a = b.attention
  const hasAny = a.pending_approval.length + a.awaiting_acceptance.length + a.unfinished.length + a.blocking_decisions.length + a.open_issues.length
  if (!hasAny) return null
  return (
    <Block title="需要关注">
      <div className="grid gap-4 md:grid-cols-2">
        {a.pending_approval.length > 0 && (
          <div>
            <h3 className="mb-1 text-xs font-semibold text-orange-800">待审批的计划（{a.pending_approval.length}）</h3>
            <StepLinks pid={pid} items={a.pending_approval} tab="plan" />
          </div>
        )}
        {a.awaiting_acceptance.length > 0 && (
          <div>
            <h3 className="mb-1 text-xs font-semibold text-sky-800">待验收（{a.awaiting_acceptance.length}）</h3>
            <StepLinks pid={pid} items={a.awaiting_acceptance} />
          </div>
        )}
        {a.unfinished.length > 0 && (
          <div>
            <h3 className="mb-1 text-xs font-semibold text-slate-700">进行中 / 部分完成 / 已停止（{a.unfinished.length}）</h3>
            <StepLinks pid={pid} items={a.unfinished} />
          </div>
        )}
        {a.open_issues.length > 0 && (
          <div>
            <h3 className="mb-1 text-xs font-semibold text-slate-700">
              未解决的问题（{a.open_issues.length}）
              <Link to={`/p/${pid}/tracker`} className="ml-2 font-normal text-blue-700 underline">
                去处理
              </Link>
            </h3>
            <ul className="space-y-1 text-sm">
              {a.open_issues.slice(0, 8).map((i) => (
                <li key={i.id}>
                  <span className="font-mono text-xs text-slate-500">{i.id}</span> {i.title}
                  <span className="ml-1 text-xs text-slate-500">
                    {i.severity}
                    {i.blocking ? ' · 阻塞' : ''}
                    {i.step ? ` · ${i.step}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      {a.blocking_decisions.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-1 text-xs font-semibold text-amber-900">
            阻塞后续执行、尚未裁定的待决事项（{a.blocking_decisions.length}）
            <Link to={`/p/${pid}/tracker?tab=pending`} className="ml-2 font-normal text-blue-700 underline">
              全部待决事项
            </Link>
          </h3>
          <div className="space-y-1.5">
            {groupPending(a.blocking_decisions).map(([source, items]) => (
              <details key={source} className="rounded border border-amber-200 bg-amber-50/50 px-2 py-1 text-sm">
                <summary className="cursor-pointer">
                  {items[0].step && <b>{items[0].step}</b>} {items.length} 项（{items[0].id}
                  {items.length > 1 ? `–${items[items.length - 1].id}` : ''}）
                  {items[0].source && <span className="ml-1 text-xs text-slate-500">出自项目文件 {source}</span>}
                </summary>
                <ul className="mt-1 space-y-0.5 pl-4">
                  {items.map((it) => (
                    <li key={it.id} className="list-disc">
                      <span className="font-mono text-xs text-slate-500">{it.id}</span> {it.question}
                      {it.recommendation && <span className="text-[13px] text-slate-600"> — 推荐：{it.recommendation}</span>}
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
        </div>
      )}
    </Block>
  )
}

/** 迭代情况：只有出现了多轮、返工、回退、失败或无效的尝试才值得一张表；全是一轮一次成功就不占地方。 */
function Iterations({ pid, b }: { pid: string; b: Board }) {
  const rows = b.iterations.filter((r) => r.revisions > 1 || r.loops > 0 || r.back_edges > 0 || r.failed > 0 || r.invalid > 0)
  if (!rows.length) return null
  const has = { loops: rows.some((r) => r.loops), back: rows.some((r) => r.back_edges), invalid: rows.some((r) => r.invalid) }
  return (
    <Block title="迭代情况">
      <div className="overflow-x-auto">
        <table className="tabular w-full text-[13px]">
          <thead className="text-left text-xs text-slate-500">
            <tr>
              <th className="py-1 pr-3 font-normal">步骤</th>
              <th className="py-1 pr-3 font-normal">状态</th>
              <th className="py-1 pr-3 text-right font-normal">轮次</th>
              {has.loops && <th className="py-1 pr-3 text-right font-normal">返工</th>}
              {has.back && <th className="py-1 pr-3 text-right font-normal">回退</th>}
              <th className="py-1 pr-3 text-right font-normal">运行（成功 / 失败）</th>
              {has.invalid && <th className="py-1 pr-3 text-right font-normal">无效或无结论</th>}
              <th className="py-1 font-normal">最近运行</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.step} className="border-t border-slate-100">
                <td className="py-1 pr-3">
                  <Link to={`/p/${pid}/steps/${r.step}`} className="text-blue-700 hover:underline">
                    {r.step} {r.title}
                  </Link>
                </td>
                <td className="py-1 pr-3">
                  <StatusBadge status={r.status} />
                </td>
                <td className="py-1 pr-3 text-right">{r.revisions}</td>
                {has.loops && <td className="py-1 pr-3 text-right">{r.loops || '—'}</td>}
                {has.back && <td className="py-1 pr-3 text-right">{r.back_edges || '—'}</td>}
                <td className="py-1 pr-3 text-right">{r.runs ? `${r.runs}（${r.succeeded} / ${r.failed}）` : '—'}</td>
                {has.invalid && <td className="py-1 pr-3 text-right">{r.invalid || '—'}</td>}
                <td className="py-1 text-xs text-slate-600">{fmtTime(r.last_run)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Block>
  )
}

const KIND: Record<ActivityEvent['kind'], { label: string; icon: typeof Play }> = {
  commit: { label: '提交', icon: GitCommitHorizontal },
  run: { label: '运行', icon: Play },
  revision: { label: '轮次', icon: RotateCcw },
  issue: { label: '问题', icon: CircleAlert },
  decision: { label: '决策', icon: Gavel },
  pending: { label: '裁定', icon: CircleHelp },
}

const TITLE_MAX = 72

/** 提交说明常常是一整段流水账，这里只露第一句，点一下再看全。 */
function EventTitle({ text }: { text: string }) {
  const [full, setFull] = useState(false)
  const cut = text.length > TITLE_MAX
  if (!cut) return <>{text}</>
  const head = full ? text : text.slice(0, TITLE_MAX).replace(/[，。；、,;:：—\-]+$/, '')
  return (
    <>
      {head}
      {!full && '…'}
      <button type="button" onClick={() => setFull(!full)} className="ml-1 text-xs text-blue-700 underline underline-offset-2">
        {full ? '收起' : '展开'}
      </button>
    </>
  )
}

export function Activity({ pid, events }: { pid: string; events: ActivityEvent[] }) {
  const [all, setAll] = useState(false)
  if (!events.length) return <p className="text-sm text-slate-500">还没有动态。</p>
  const shown = all ? events : events.slice(0, 20)
  return (
    <>
      <ol className="space-y-1">
        {shown.map((e, i) => {
          const k = KIND[e.kind]
          return (
            <li key={i} className="flex items-baseline gap-2 text-[13px]">
              <span className="tabular w-32 shrink-0 text-xs text-slate-500">{fmtTime(e.time).slice(0, 16)}</span>
              <span className="inline-flex w-12 shrink-0 items-center gap-1 text-xs text-slate-600">
                <k.icon className="h-3 w-3 self-center" aria-hidden />
                {k.label}
              </span>
              <span className="min-w-0 flex-1">
                {e.kind === 'run' && e.ref ? (
                  <Link to={`/p/${pid}/runs/${e.ref}`} className={`hover:underline ${e.status === 'failed' ? 'text-red-700' : ''}`}>
                    {e.title}
                  </Link>
                ) : (
                  <EventTitle text={e.title} />
                )}
              </span>
              {e.step && (
                <Link to={`/p/${pid}/steps/${e.step}`} className="shrink-0 text-xs text-blue-700 hover:underline">
                  {e.step}
                </Link>
              )}
            </li>
          )
        })}
      </ol>
      {events.length > 20 && (
        <button onClick={() => setAll(!all)} className="mt-2 text-xs text-slate-600 underline">
          {all ? '收起' : `显示全部 ${events.length} 条`}
        </button>
      )}
    </>
  )
}
