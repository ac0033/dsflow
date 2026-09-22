import { useState } from 'react'
import { Link } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, BookOpen, Merge, Table2, X } from 'lucide-react'
import { api } from '../../api'
import { useAsk } from '../../components/ask/AskContext'
import { fmtInt } from '../../lib/format'
import type { StepTable, TableSource } from '../../types'

/** 一列在这一步里发生的变化 */
export type ColKind = '新增' | '消失' | '取值有变化'

/** 比对两张表得到的「取值有变化」的列，以及各自变在哪 */
export interface ColChange {
  cols: string[]
  flags: Record<string, string[]>
}

/*
 * 增减量：这一步把哪几张表改成 / 合并成了哪张表，行和列各自怎么变。
 *
 * 这里只讲变化，不再铺开数据全貌——同一张表的整张内容在「后存量」里打开就行，两处重复没有意义。
 * 三种变化各一种读法：新增是「上游表 → 新表」，更新是「旧版本 → 新版本」，退出是「这张表交给谁接手」。
 */

const BADGE: Record<string, string> = {
  新增: 'bg-blue-600 text-white',
  更新: 'bg-amber-400 text-amber-950',
  退出: 'bg-slate-200 text-slate-600',
}

const shape = (rows?: number | null, cols?: number | null) =>
  rows == null || cols == null ? '还没转换，读不到行列数' : `${fmtInt(rows)} 行 × ${cols} 列`

/** 差多少：0 说"没变"，其余带正负号。 */
const delta = (a?: number | null, b?: number | null) => {
  if (a == null || b == null) return null
  const d = b - a
  return { d, text: d === 0 ? '没变' : d > 0 ? `+${fmtInt(d)}` : `−${fmtInt(-d)}` }
}

export default function StepDelta({ added, updated, retired, checked, pid, stepId, revId, changed, onCompare, comparing, errors }: {
  added: StepTable[]
  updated: StepTable[]
  retired: StepTable[]
  checked: StepTable[]
  pid: string
  stepId: string
  revId: string
  /** 已经比对出来的「取值有变化」的列，按表的路径存 */
  changed: Record<string, ColChange>
  /** 让上层去跑一次两张表的比对 */
  onCompare: (t: StepTable) => void
  comparing: string | null
  errors: Record<string, string>
}) {
  const card = (t: StepTable) => (
    <Card key={t.path} t={t} pid={pid} stepId={stepId} revId={revId} changed={changed[t.path]}
          onCompare={() => onCompare(t)} comparing={comparing === t.path} error={errors[t.path]} />
  )
  return (
    <div className="space-y-2">
      {added.map(card)}
      {updated.map(card)}
      {retired.map(card)}
      {checked.length > 0 && (
        <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
          <b className="font-medium text-slate-700">只读没改 {checked.length} 张</b>：{checked.map((t) => t.name).join('、')}
          。这一步读了它们，没有改动文件。
        </p>
      )}
    </div>
  )
}

function Card({ t, pid, stepId, revId, changed, onCompare, comparing, error }: {
  t: StepTable
  pid: string
  stepId: string
  revId: string
  changed?: ColChange
  onCompare: () => void
  comparing: boolean
  error?: string
}) {
  const sources = t.role === '新增' ? t.sources ?? [] : []
  const merged = sources.length > 1
  // 行列的对照基准：新增跟上游的主表比，更新跟自己的旧版本比，退出跟接手的新表比
  const base =
    t.role === '更新'
      ? { name: `旧版本 ${t.previous_version ?? '?'}`, rows: t.previous_rows, columns: t.previous_columns }
      : (sources.find((s) => s.name === t.diff_base) ?? sources[0] ?? null)
  const result = { name: t.name, rows: t.rows, columns: t.columns }
  const rowChange = delta(base?.rows, result.rows)
  const colChange = delta(base?.columns, result.columns)

  // 退出：接手的那张表就在上面的「新增」里，行列怎么变那里已经讲过，这里只说这张表交给了谁
  if (t.role === '退出')
    return (
      <article className="flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-slate-300 bg-white px-3 py-2">
        <span className={`rounded px-1.5 py-0.5 text-[11px] ${BADGE['退出']}`}>退出</span>
        <b className="text-sm text-slate-500 line-through">{t.name}</b>
        <span className="tabular text-xs text-slate-500">{shape(t.rows, t.columns)}</span>
        <ArrowRight className="h-3.5 w-3.5 text-slate-400" aria-hidden />
        <span className="text-xs text-slate-700">
          交给 <b>{t.retired_by}</b>
          <span className="tabular ml-1 text-slate-500">{shape(t.retired_by_rows, t.retired_by_columns)}</span>
        </span>
        <span className="ml-auto text-xs text-slate-500">以后不再用它，后存量里也不再有它</span>
      </article>
    )

  // 没有可比的上一张表（比如说明卡声明的产物）：不摆变化的架子，一行说清它是什么、多大
  if (!base)
    return (
      <article className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2">
        <span className={`rounded px-1.5 py-0.5 text-[11px] ${BADGE[t.role] ?? 'bg-slate-200 text-slate-700'}`}>{t.role}</span>
        <b className="text-sm text-slate-900">{result.name}</b>
        <span className="text-xs text-slate-500">{headline(t, sources)}</span>
        <span className="tabular ml-auto text-xs text-slate-600">
          {t.missing ? <span className="text-red-600">文件已经不在项目里</span> : t.ready ? shape(result.rows, result.columns) : '还没转换，在后存量里打开一次就能看到行列数'}
        </span>
      </article>
    )

  return (
    <article className="rounded-xl border border-slate-200 bg-white">
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-2">
        <span className={`rounded px-1.5 py-0.5 text-[11px] ${BADGE[t.role] ?? 'bg-slate-200 text-slate-700'}`}>{t.role}</span>
        <b className="text-sm text-slate-900">{result.name}</b>
        <span className="text-xs text-slate-500">{headline(t, sources)}</span>
        {t.missing && <span className="text-xs text-red-600">文件已经不在项目里</span>}
      </header>

      {/* 怎么变过来的：左边是变之前的表，右边是变之后的表 */}
      <div className="flex flex-wrap items-center gap-2 px-3 py-2.5">
        <div className="min-w-0 flex-1 space-y-1">
          {t.role === '新增' &&
            (sources.length ? (
              sources.map((s) => <From key={s.name} s={s} main={s.name === t.diff_base && merged} />)
            ) : (
              <p className="rounded-lg border border-dashed border-slate-300 px-2.5 py-1.5 text-xs text-slate-500">
                没有登记上游表，看不出它是从哪张表做出来的。
              </p>
            ))}
          {t.role === '更新' && <From s={{ name: `${t.name}（旧版本 ${t.previous_version ?? '?'}）`, path: t.previous_path ?? null, rows: t.previous_rows ?? null, columns: t.previous_columns ?? null, missing: false, ready: true }} />}
        </div>
        <div className="flex shrink-0 flex-col items-center px-1 text-[11px] text-blue-600">
          {merged ? <Merge className="h-4 w-4 rotate-90" aria-hidden /> : <ArrowRight className="h-4 w-4" aria-hidden />}
          <span>{merged ? '合并成' : t.role === '更新' ? '重算成' : '做成'}</span>
        </div>
        <div className="min-w-0 flex-1">
          <To name={result.name} rows={result.rows} columns={result.columns} />
        </div>
      </div>

      {/* 行和列各变了多少 */}
      <div className="grid gap-x-6 gap-y-1 border-t border-slate-100 px-3 py-2 text-xs sm:grid-cols-2">
        <Line label="行" a={base?.rows} b={result.rows} change={rowChange} />
        <Line label="列" a={base?.columns} b={result.columns} change={colChange} />
      </div>

      <Columns t={t} baseName={base?.name} pid={pid} stepId={stepId} revId={revId} changed={changed}
               onCompare={onCompare} comparing={comparing} error={error} />
    </article>
  )
}

/** 标题后面那半句：这张表是怎么来的、和谁比。 */
function headline(t: StepTable, sources: TableSource[]): string {
  if (t.role === '退出') return `被 ${t.retired_by} 替代，以后不再用它`
  if (t.role === '更新') return `同一张表重算了一遍：版本 ${t.previous_version ?? '?'} → ${t.version ?? '?'}`
  if (sources.length > 1) return `由 ${sources.length} 张表合并而成`
  if (sources.length === 1) return `由 ${sources[0].name} 做出来`
  return t.declared ? '说明卡里声明的产物' : '这一步新产出的表'
}

function From({ s, main = false }: { s: TableSource; main?: boolean }) {
  return (
    <div className={`rounded-lg border px-2.5 py-1.5 ${main ? 'border-slate-400 bg-slate-50' : 'border-slate-200 bg-white'}`}>
      <p className="truncate text-xs font-medium text-slate-700" title={s.path ?? s.name}>
        {s.name}
        {main && <span className="ml-1 rounded bg-slate-200 px-1 text-[10px] font-normal text-slate-600">主表</span>}
      </p>
      <p className="tabular text-[11px] text-slate-500">{s.missing ? '这张表不在项目里' : shape(s.rows, s.columns)}</p>
    </div>
  )
}

function To({ name, rows, columns }: { name: string; rows?: number | null; columns?: number | null }) {
  return (
    <div className="rounded-lg border border-blue-300 bg-blue-50 px-2.5 py-1.5">
      <p className="flex items-center gap-1 truncate text-xs font-semibold text-slate-900">
        <Table2 className="h-3.5 w-3.5 shrink-0 text-blue-600" aria-hidden />
        {name}
      </p>
      <p className="tabular text-[11px] text-slate-600">{shape(rows, columns)}</p>
    </div>
  )
}

function Line({ label, a, b, change }: { label: string; a?: number | null; b?: number | null; change: { d: number; text: string } | null }) {
  return (
    <p className="tabular flex flex-wrap items-baseline gap-1.5">
      <span className="w-6 text-slate-500">{label}</span>
      {a == null || b == null ? (
        <span className="text-slate-400">两边都转换过才数得出{label}数</span>
      ) : (
        <>
          <span className="text-slate-700">{fmtInt(a)}</span>
          <ArrowRight className="h-3 w-3 text-slate-400" aria-hidden />
          <b className="text-slate-900">{fmtInt(b)}</b>
          {change && (
            <span className={`rounded px-1.5 ${change.d === 0 ? 'bg-slate-100 text-slate-500' : change.d > 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>
              {change.text}
            </span>
          )}
        </>
      )}
    </p>
  )
}

const SHOW = 12

/** 一列的三种变化，颜色和「打开全貌」里表头的标色对应。 */
const COL_STYLE: Record<ColKind, string> = {
  新增: 'bg-emerald-50 text-emerald-800 ring-emerald-200 hover:bg-emerald-100',
  消失: 'bg-rose-50 text-rose-800 line-through ring-rose-200 hover:bg-rose-100',
  取值有变化: 'bg-sky-50 text-sky-800 ring-sky-200 hover:bg-sky-100',
}

/**
 * 变了哪些列：新增的、消失的、取值有变化的，每个列名都能点开看它为什么变。
 *
 * 「取值有变化」要把两张表的画像各做一遍才知道，所以由用户点一下再算（大表要等），算完这几列在
 * 「打开全貌」里也会标出来。点开一个列名，下面显示讲解里说过它的那句话，一键跳到讲解的那一格。
 */
function Columns({ t, baseName, pid, stepId, revId, changed, onCompare, comparing, error }: {
  t: StepTable
  baseName?: string
  pid: string
  stepId: string
  revId: string
  changed?: ColChange
  onCompare: () => void
  comparing: boolean
  error?: string
}) {
  const [all, setAll] = useState(false)
  const [picked, setPicked] = useState<{ name: string; kind: ColKind } | null>(null)
  const d = t.diff
  const cut = (list: string[]) => (all ? list : list.slice(0, SHOW))
  const chip = (name: string, kind: ColKind) => (
    <button
      key={`${kind}-${name}`}
      type="button"
      onClick={() => setPicked(picked?.name === name && picked.kind === kind ? null : { name, kind })}
      className={`rounded px-1.5 ring-1 ${COL_STYLE[kind]} ${picked?.name === name && picked.kind === kind ? 'ring-2' : ''}`}
      title="点一下看这一列为什么变、讲解里在哪说的"
    >
      {name}
    </button>
  )

  if (!d)
    return <p className="border-t border-slate-100 px-3 py-1.5 text-xs text-slate-500">没有可比的上游表，列的变化无从比起。</p>
  if (!d.known)
    return (
      <p className="border-t border-slate-100 px-3 py-1.5 text-xs text-slate-500">
        这两张表里有一张还没转换过，列的变化暂时比不出来。在「后存量」里各打开一次，回到这里就能比。
      </p>
    )

  const same = !d.added.length && !d.removed.length
  return (
    <div className="space-y-1 border-t border-slate-100 px-3 py-2 text-xs">
      {same && <p className="text-slate-600">列名和{baseName ?? '上一张表'}完全一样（{d.kept} 列），变的是行与取值。</p>}
      {d.added.length > 0 && (
        <p className="flex flex-wrap items-baseline gap-1">
          <span className="text-emerald-700">新增 {d.added.length} 列</span>
          {cut(d.added).map((c) => chip(c, '新增'))}
        </p>
      )}
      {d.removed.length > 0 && (
        <p className="flex flex-wrap items-baseline gap-1">
          <span className="text-rose-700">消失 {d.removed.length} 列</span>
          {cut(d.removed).map((c) => chip(c, '消失'))}
        </p>
      )}

      {/* 原来就有的列，这一步把值改了的 */}
      {changed ? (
        changed.cols.length ? (
          <p className="flex flex-wrap items-baseline gap-1">
            <span className="text-sky-700">取值有变化 {changed.cols.length} 列</span>
            {cut(changed.cols).map((c) => chip(c, '取值有变化'))}
            <span className="text-slate-400">（空值数、取值范围或不同值个数和上游不一样）</span>
          </p>
        ) : (
          <p className="text-slate-500">两边共有的 {d.kept} 列里，没有一列的空值数、取值范围或不同值个数发生变化。</p>
        )
      ) : (
        <p className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onCompare}
            disabled={comparing}
            className="rounded border border-sky-300 px-2 py-0.5 text-sky-700 hover:bg-sky-50 disabled:opacity-50"
          >
            {comparing ? '正在比对两张表…' : '看看哪些原有的列被改了值'}
          </button>
          <span className="text-slate-400">要把两张表各做一遍画像，大表要等一会儿；算完这几列在「打开全貌」里也会标色。</span>
        </p>
      )}
      {error && <p className="text-rose-700">{error}</p>}

      <p className="text-slate-500">
        保留 {d.kept} 列
        {(d.added.length > SHOW || d.removed.length > SHOW || (changed?.cols.length ?? 0) > SHOW) && (
          <button type="button" onClick={() => setAll(!all)} className="ml-2 text-blue-700 hover:underline">
            {all ? '收起列名' : '展开全部列名'}
          </button>
        )}
      </p>

      {picked && (
        <ColumnWhy
          pid={pid}
          stepId={stepId}
          revId={revId}
          name={picked.name}
          kind={picked.kind}
          flags={changed?.flags[picked.name] ?? []}
          onClose={() => setPicked(null)}
        />
      )}
    </div>
  )
}

/** 点开一个列名：这一列怎么变的、讲解里哪一段说过它、跳过去看那一格。 */
function ColumnWhy({ pid, stepId, revId, name, kind, flags, onClose }: {
  pid: string
  stepId: string
  revId: string
  name: string
  kind: ColKind
  flags: string[]
  onClose: () => void
}) {
  const q = useQuery({
    queryKey: ['colnotes', pid, stepId, revId, name],
    queryFn: () => api.columnNotes(pid, stepId, { columns: [name], rev: revId }),
    staleTime: 60_000,
  })
  const notes = q.data?.notes[name] ?? []
  const ask = useAsk()
  return (
    <div className="mt-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <p className="flex flex-wrap items-center gap-2">
        <b className="text-sm text-slate-900">{name}</b>
        <span className={`rounded px-1.5 ring-1 ${COL_STYLE[kind]}`}>{kind}</span>
        {flags.length > 0 && <span className="text-slate-500">和上游比：{flags.join('、')}</span>}
        <button type="button" onClick={onClose} className="ml-auto text-slate-400 hover:text-slate-700" aria-label="收起这一列的说明">
          <X className="h-3.5 w-3.5" />
        </button>
      </p>
      {q.isLoading && <p className="mt-1 text-slate-500">正在从讲解里找这一列…</p>}
      {q.error && <p className="mt-1 text-rose-700">{(q.error as Error).message}</p>}
      {q.data && !notes.length && (
        <p className="mt-1 leading-relaxed text-slate-600">
          讲解和 notebook 里都没有提到「{name}」，说不出它为什么变。
          {ask && (
            <button
              type="button"
              onClick={() => ask.ask({ quote: `${name}（${kind}）` })}
              className="ml-1 text-blue-700 hover:underline"
            >
              问 AI
            </button>
          )}
        </p>
      )}
      <ul className="mt-1 space-y-1">
        {notes.map((n, i) => (
          <li key={i} className="rounded border border-slate-200 bg-white px-2 py-1">
            <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
              <span className={`rounded px-1 ${n.source === '讲解' ? 'bg-blue-50 text-blue-700' : 'bg-slate-100 text-slate-600'}`}>{n.source}</span>
              <span>{n.where}</span>
              {n.title && <span className="truncate text-slate-600">{n.title}</span>}
              {(n.part || n.cell) && (
                <Link
                  to={`/p/${pid}/steps/${stepId}?tab=guide${n.part ? `&part=${n.part}` : ''}${n.cell ? `&cell=${n.cell}` : ''}`}
                  className="ml-auto inline-flex items-center gap-0.5 text-blue-700 hover:underline"
                >
                  <BookOpen className="h-3 w-3" aria-hidden />
                  跳到讲解
                </Link>
              )}
            </p>
            <p className={`mt-0.5 leading-relaxed text-slate-700 ${n.source === '讲解' ? '' : 'font-mono text-[11px]'}`}>{n.quote}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}
