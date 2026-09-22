import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Table2, X } from 'lucide-react'
import { api } from '../../api'
import JobProgress from '../../components/JobProgress'
import VirtualTable from '../../components/VirtualTable'
import { fmtInt } from '../../lib/format'
import { useJob } from '../../lib/useJob'
import { useRowBlocks } from '../../lib/useRowBlocks'
import StepDelta, { type ColChange } from './StepDelta'
import type { CompareResult, StepTable } from '../../types'

/*
 * 数据（数据层）：以数据表为主线的存量账。
 * 原存量 = 执行前已有的、有用的最终文件；增减量 = 这一步新增 / 更新 / 退出了什么（没有就空着）；
 * 后存量 = 执行完之后有用的最终文件。每张表都能整张打开。
 * 产物只算有用的最终文件：登记过的数据集、说明卡声明了用途的产物、报告。中间结果与核对清单不列（口径写在 docs/agent-guide.md）。
 */

const ROLE_STYLE: Record<string, string> = {
  核对: 'border-violet-300 bg-violet-50 text-violet-800',
  读取: 'border-slate-300 bg-slate-50 text-slate-700',
}

const size = (b?: number | null) => (b == null ? '' : b >= 1e6 ? `${Math.round(b / 1e6)} MB` : `${Math.round(b / 1e3)} KB`)
/** 整表转 Parquet 实测约 145 MB / 335 秒，按这个估给用户一个心理预期。 */
const minutes = (b?: number | null) => Math.max(1, Math.round((((b ?? 0) / 1e6 / 145) * 335) / 60))
/** 这么小的表转一次只要几秒，不用问，打开就转 */
const AUTO_PREPARE_BYTES = 30e6

export default function StepTables({ pid, stepId, revId, open, onOpen }: {
  pid: string
  stepId: string
  revId: string
  /** 正在整张看的表（项目内相对路径），放在地址栏里，讲解 / 看板跳过来时直接带上 */
  open?: string | null
  onOpen: (path: string | null) => void
}) {
  const q = useQuery({ queryKey: ['stock', pid, stepId, revId], queryFn: () => api.stepStock(pid, stepId, revId), staleTime: 60_000 })
  // 「取值有变化」的列：要把两张表各做一遍画像才知道，所以由用户在增减量里点一下再算，算完两处共用
  const [changed, setChanged] = useState<Record<string, ColChange>>({})
  const [colErrors, setColErrors] = useState<Record<string, string>>({})
  const [comparing, setComparing] = useState<string | null>(null)
  const compare = useJob<CompareResult>((result) => {
    const cols = (result?.columns ?? []).filter((c) => c.flags.length)
    setChanged((now) => ({
      ...now,
      [result.b]: { cols: cols.map((c) => c.name), flags: Object.fromEntries(cols.map((c) => [c.name, c.flags])) },
    }))
    setComparing(null)
  })
  useEffect(() => {
    if (compare.job?.status === 'failed') {
      setColErrors((now) => (comparing ? { ...now, [comparing]: compare.job?.error ?? '比对没能完成' } : now))
      setComparing(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compare.job?.status])
  const startCompare = async (t: StepTable) => {
    const base = t.role === '更新' ? t.previous_path : t.diff_base_path
    if (!base) return setColErrors((now) => ({ ...now, [t.path]: '没有可比的上游表，比不出取值变化。' }))
    setColErrors((now) => ({ ...now, [t.path]: '' }))
    setComparing(t.path)
    try {
      compare.start(await api.compare(pid, { a: base, b: t.path, key: [], segment: null }))
    } catch (e) {
      setColErrors((now) => ({ ...now, [t.path]: (e as Error).message }))
      setComparing(null)
    }
  }
  if (q.isLoading) return <p className="text-sm text-slate-500">读取存量账…</p>
  if (q.error) return <p className="text-sm text-red-600">{(q.error as Error).message}</p>
  const s = q.data
  if (!s) return null
  const { added, updated, retired, checked } = s.delta
  const middles = s.middles ?? []
  const all = [...s.before, ...added, ...updated, ...retired, ...checked, ...s.after, ...middles]
  const opened = open ? all.find((t) => t.path === open) ?? null : null
  // 本步只读没改的表通常就在原存量里：在那张卡上标「本步读取」，不再单列一遍
  const used = new Map(checked.map((t) => [t.name, t.role]))
  const before = s.before.map((t) => (used.has(t.name) ? { ...t, used_as: used.get(t.name) } : t))
  const checkedOnly = checked.filter((t) => !s.before.some((b) => b.name === t.name))
  const card = (t: StepTable & { used_as?: string }) => <TableCard key={`${t.role}-${t.path}`} t={t} active={opened?.path === t.path} onOpen={() => onOpen(t.path)} />
  const grid = (items: (StepTable & { used_as?: string })[]) => <div className="grid gap-2 md:grid-cols-2">{items.map(card)}</div>
  const nothing = !all.length

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-blue-200 bg-gradient-to-b from-blue-50/60 to-white px-4 py-3 text-sm">
        {s.changes_data ? (
          <p className="flex flex-wrap items-center gap-1.5">
            <span className="text-slate-500">执行前</span>
            <b className="rounded bg-white px-1.5 py-0.5 ring-1 ring-slate-200">{s.before.length} 张有用的表</b>
            <ArrowRight className="h-3.5 w-3.5 text-blue-500" aria-hidden />
            {added.length > 0 && <b className="rounded bg-blue-600 px-1.5 py-0.5 text-white">新增 {added.length}</b>}
            {updated.length > 0 && <b className="rounded bg-amber-400 px-1.5 py-0.5 text-amber-950">更新 {updated.length}</b>}
            {retired.length > 0 && <b className="rounded bg-slate-200 px-1.5 py-0.5 text-slate-600">退出 {retired.length}</b>}
            <ArrowRight className="h-3.5 w-3.5 text-blue-500" aria-hidden />
            <span className="text-slate-500">执行后</span>
            <b className="rounded bg-white px-1.5 py-0.5 ring-1 ring-slate-200">{s.after.length} 张</b>
          </p>
        ) : (
          <p className="text-slate-700">
            <b>这一步没有新增、更新或退出任何数据表。</b>
            {checked.length > 0 && '它只读取了标有「本步核对」的表，重新计算并核对了其中的数字，没有改动原文件。'}
            {nothing && '它也还没有和任何数据表挂钩。'}
          </p>
        )}
      </section>

      {opened && <Opened pid={pid} t={opened} changed={changed[opened.path]?.cols} onClose={() => onOpen(null)} />}
      {open && !opened && <p className="text-xs text-amber-800">这一步的存量账里没有 {open}。</p>}

      <Section title="原存量" note={`执行前 ${s.before.length} 张`}>
        {before.length ? grid(before) : <p className="text-sm text-slate-400">执行前还没有任何登记的表。</p>}
      </Section>

      <Section title="增减量" note="只讲变化：哪几张表改成 / 合并成了哪张表，行与列各变了多少；点一个列名看它为什么变。整张内容在下面的后存量里打开">
        {nothing ? (
          <Empty stepId={stepId} />
        ) : (
          <StepDelta
            added={added} updated={updated} retired={retired} checked={checkedOnly}
            pid={pid} stepId={stepId} revId={revId}
            changed={changed} onCompare={startCompare} comparing={comparing} errors={colErrors}
          />
        )}
        {compare.job && comparing && <JobProgress job={compare.job} />}
      </Section>

      <Section title="后存量" note={`执行后 ${s.after.length} 张`}>
        {s.after.length ? grid(s.after) : <p className="text-sm text-slate-400">执行后没有任何登记的表。</p>}
      </Section>

      {middles.length > 0 && (
        <details className="rounded-xl border border-slate-200 bg-white px-3 py-2">
          <summary className="cursor-pointer text-xs text-slate-600">
            <span className="font-semibold text-slate-700">中间产物</span>
            <span className="ml-2 text-slate-400">
              本轮留下的 {middles.length} 个数据文件，没进存量账（核对清单、台账这类）。报告与说明在「产物」里看。
            </span>
          </summary>
          <div className="mt-2">{grid(middles)}</div>
        </details>
      )}
    </div>
  )
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-1.5 flex flex-wrap items-baseline gap-2 text-xs tracking-wider text-slate-400">
        <span className="font-semibold text-slate-600">{title}</span>
        {note && <span className="tracking-normal">· {note}</span>}
      </h3>
      {children}
    </section>
  )
}

function Empty({ stepId }: { stepId: string }) {
  return (
    <p className="rounded-lg border border-dashed border-slate-300 p-4 text-sm leading-relaxed text-slate-600">
      这一步还没有和任何数据表挂钩。产出的表用
      <code className="mx-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs">dsflow data add &lt;项目&gt; &lt;文件&gt; --name 名称 --parent 上游 --produced-by {stepId} [--replaces 被替代的表]</code>
      登记；只读不改的表用
      <code className="mx-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs">dsflow data link &lt;项目&gt; &lt;名称&gt; --step {stepId} --role 核对</code>
      挂上来；报告和说明卡里声明了用途的产物会自动出现。
    </p>
  )
}

/** 一句来历。分组标题已经说明了新增 / 更新 / 退出 / 存量，这里只补分组说不清的：版本、替代关系、上游步骤。 */
function origin(t: StepTable): string {
  if (t.role === '更新') return `旧版本 ${t.previous_version ?? '?'} → 新版本 ${t.version ?? '?'}`
  if (t.role === '退出') return `被 ${t.retired_by} 替代`
  if (t.produced_by && t.role !== '新增') return `来自 ${t.produced_by}`
  return t.stage_label === '原始' ? '原始数据' : ''
}

export function TableCard({ t, active, onOpen }: { t: StepTable & { used_as?: string }; active: boolean; onOpen: () => void }) {
  const gone = t.role === '退出'
  return (
    <div className={`rounded-lg border bg-white ${active ? 'border-blue-400 ring-1 ring-blue-200' : gone ? 'border-dashed border-slate-300' : 'border-slate-200'}`}>
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <b className={`text-sm ${gone ? 'text-slate-500 line-through' : 'text-slate-900'}`} title={t.path}>{t.name}</b>
        {t.used_as && <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[11px] ${ROLE_STYLE[t.used_as] ?? ''}`}>本步{t.used_as}</span>}
        <span className="tabular text-xs text-slate-500">
          {t.missing ? <span className="text-red-600">文件不在</span> : t.ready ? `${fmtInt(t.rows ?? 0)} 行 × ${t.columns} 列` : size(t.size)}
        </span>
        {origin(t) && <span className="text-xs text-slate-400">{origin(t)}</span>}
        <button onClick={onOpen} className={`ml-auto inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs ${active ? 'border-blue-500 bg-blue-600 text-white' : 'border-slate-300 text-slate-700 hover:bg-slate-50'}`}>
          <Table2 className="h-3.5 w-3.5" aria-hidden />
          {active ? '正在看' : '打开全貌'}
        </button>
      </div>
      {t.note && (
        <p className={`truncate px-3 pb-1.5 text-xs leading-relaxed ${t.note_missing ? 'text-slate-400' : 'text-slate-500'}`} title={t.note}>
          {t.note}
        </p>
      )}
    </div>
  )
}

/** 正在整张看的表：一个面板，带名字、角色和关闭；表格本身行列双向虚拟滚动。 */
function Opened({ pid, t, changed, onClose }: { pid: string; t: StepTable; changed?: string[]; onClose: () => void }) {
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [t.path])
  const highlight = useMemo(() => new Set(t.diff?.added ?? []), [t.diff])
  const touched = useMemo(() => new Set(changed ?? []), [changed])
  return (
    <section ref={ref} className="rounded-xl border border-blue-400 bg-white shadow-sm">
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-2">
        <b className="text-sm">{t.name}</b>
        <span className="truncate text-[11px] text-slate-400" title={t.path}>{t.path}</span>
        <button onClick={onClose} className="ml-auto inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50">
          <X className="h-3.5 w-3.5" aria-hidden />
          收起
        </button>
      </header>
      <Full pid={pid} t={t} highlight={highlight} touched={touched} />
    </section>
  )
}

/** 整张表打开：行列双向虚拟滚动，只取可视区。没转成 Parquet 的先转一次；小表自动转，大表先问。 */
function Full({ pid, t, highlight, touched }: { pid: string; t: StepTable; highlight: Set<string>; touched: Set<string> }) {
  const job = useJob<unknown>(() => meta.refetch())
  const meta = useQuery({ queryKey: ['meta', pid, t.path], queryFn: () => api.meta(pid, t.path) })
  const ready = meta.data?.ready ?? t.ready
  const fetchBlock = useCallback((offset: number, limit: number) => api.table(pid, { path: t.path, offset, limit }), [pid, t.path])
  const blocks = useRowBlocks(fetchBlock, ready ? t.path : `${t.path}:未就绪`)
  const small = (t.size ?? 0) < AUTO_PREPARE_BYTES
  const [auto, setAuto] = useState(false)
  useEffect(() => {
    if (meta.data && !meta.data.ready && small && !t.missing && !auto && !job.running) {
      setAuto(true)
      api.prepare(pid, t.path).then(job.start)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta.data?.ready, small, t.path])

  if (t.missing) return <p className="px-3 py-3 text-sm text-red-600">这个文件已经不在项目里了。</p>
  if (!ready)
    return (
      <div className="px-3 py-3">
        {small ? (
          <p className="text-sm text-slate-600">这张表很小，正在转成可以翻页的格式，几秒就好…</p>
        ) : (
          <>
            <p className="mb-2 text-sm leading-relaxed text-slate-600">
              这张表还没转成可以随机翻页的格式。转一次大约 <b>{minutes(t.size)} 分钟</b>（{size(t.size)}），转完会按内容缓存，以后打开是秒开；原文件不会被改动。
            </p>
            <button
              disabled={job.running}
              onClick={async () => job.start(await api.prepare(pid, t.path))}
              className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {job.running ? '正在准备…' : '准备这张表'}
            </button>
          </>
        )}
        <JobProgress job={job.job} />
      </div>
    )
  if (blocks.error) return <p className="px-3 py-3 text-sm text-red-600">{blocks.error}</p>
  if (!blocks.info) return <p className="px-3 py-3 text-sm text-slate-500">读取…</p>
  return (
    <div className="p-2">
      <div className="mb-1.5 flex flex-wrap items-center gap-2 px-1 text-[11px] text-slate-500">
        <span className="tabular">{fmtInt(blocks.info.total)} 行 × {blocks.info.columns.length} 列，整张都在这里，可以左右上下翻</span>
        {highlight.size > 0 && <span className="rounded bg-amber-100 px-1.5 text-amber-900">标黄的 {highlight.size} 列是这一步新增的</span>}
        {touched.size > 0 && <span className="rounded bg-sky-100 px-1.5 text-sky-900">标蓝的 {touched.size} 列原来就有，这一步把值改了</span>}
      </div>
      <VirtualTable columns={blocks.info.columns} count={blocks.info.total} getRow={blocks.getRow} onRange={blocks.ensure} height={560} highlight={highlight} changed={touched} resetToken={t.path} />
    </div>
  )
}
