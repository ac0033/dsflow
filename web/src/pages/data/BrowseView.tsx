import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Filter, Shuffle, X } from 'lucide-react'
import { api } from '../../api'
import ColumnPicker from '../../components/ColumnPicker'
import VirtualTable from '../../components/VirtualTable'
import { fmtInt } from '../../lib/format'
import { useRowBlocks } from '../../lib/useRowBlocks'
import type { DataColumn } from '../../types'

/** 浏览器单个元素高度有上限，超大表按每段 20 万行分段浏览。 */
const WINDOW = 200_000
const OPS = [
  ['eq', '等于'],
  ['ne', '不等于'],
  ['gt', '大于'],
  ['ge', '≥'],
  ['lt', '小于'],
  ['le', '≤'],
  ['contains', '包含'],
  ['is_null', '为空'],
  ['not_null', '不为空'],
] as const
type Op = (typeof OPS)[number][0]
interface FilterItem {
  column: string
  op: Op
  value?: string
}

export default function BrowseView({ pid, path, columns }: { pid: string; path: string; columns: DataColumn[] }) {
  const [mode, setMode] = useState<'scan' | 'sample'>('scan')
  const [sort, setSort] = useState<{ column: string; desc: boolean } | null>(null)
  const [filters, setFilters] = useState<FilterItem[]>([])
  const [windowStart, setWindowStart] = useState(0)
  const [jump, setJump] = useState('')
  const [scrollTo, setScrollTo] = useState<number | null>(null)
  const [seed, setSeed] = useState(42)

  const resetKey = JSON.stringify([path, sort, filters, windowStart])
  const fetchBlock = useCallback(
    (offset: number, limit: number) =>
      api.table(pid, { path, offset: windowStart + offset, limit, sort: sort?.column, desc: sort?.desc, filters }),
    [pid, path, sort, filters, windowStart],
  )
  const blocks = useRowBlocks(fetchBlock, resetKey)
  const sample = useQuery({
    queryKey: ['sample', pid, path, seed],
    queryFn: () => api.sample(pid, path, 500, seed),
    enabled: mode === 'sample',
  })

  const total = blocks.info?.total ?? 0
  const count = Math.max(0, Math.min(WINDOW, total - windowStart))
  const onSort = (column: string) => {
    setWindowStart(0)
    setSort((s) => (s?.column !== column ? { column, desc: false } : s.desc ? null : { column, desc: true }))
  }
  const goTo = () => {
    const n = Number(jump.replace(/[,，\s]/g, ''))
    if (!Number.isFinite(n) || n < 1 || n > total) return
    const start = Math.floor((n - 1) / WINDOW) * WINDOW
    setWindowStart(start)
    setScrollTo(n - 1 - start)
  }
  const onRange = blocks.ensure

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <div className="inline-flex rounded border border-slate-300 bg-white p-0.5">
          <button onClick={() => setMode('scan')} className={`rounded px-2 py-0.5 ${mode === 'scan' ? 'bg-slate-800 text-white' : ''}`}>
            顺序浏览
          </button>
          <button onClick={() => setMode('sample')} className={`rounded px-2 py-0.5 ${mode === 'sample' ? 'bg-slate-800 text-white' : ''}`}>
            随机抽样
          </button>
        </div>
        {mode === 'scan' ? (
          <>
            <FilterBuilder columns={columns} onAdd={(f) => { setWindowStart(0); setFilters([...filters, f]) }} />
            <span className="tabular text-slate-600">
              {blocks.info ? `${filters.length ? '筛选后 ' : '共 '}${fmtInt(total)} 行` : '加载中…'}
              {sort ? `，按「${sort.column}」${sort.desc ? '降序' : '升序'}` : '，文件原顺序'}
            </span>
            {sort && total > 1_000_000 && <span className="text-[11px] text-slate-500">（排序后越往后翻越慢：几百万行之后每页可能要几秒）</span>}
            {total > WINDOW && (
              <span className="flex items-center gap-1 text-slate-600">
                <button disabled={windowStart === 0} onClick={() => setWindowStart(windowStart - WINDOW)} className="rounded border border-slate-300 px-1.5 disabled:opacity-40">
                  上一段
                </button>
                <span className="tabular">
                  第 {fmtInt(windowStart + 1)}–{fmtInt(windowStart + count)} 行
                </span>
                <button disabled={windowStart + WINDOW >= total} onClick={() => setWindowStart(windowStart + WINDOW)} className="rounded border border-slate-300 px-1.5 disabled:opacity-40">
                  下一段
                </button>
              </span>
            )}
            <form onSubmit={(e) => { e.preventDefault(); goTo() }} className="flex items-center gap-1">
              <input value={jump} onChange={(e) => setJump(e.target.value)} placeholder="跳到第 N 行" aria-label="跳到第 N 行" className="w-24 rounded border border-slate-300 px-1.5 py-0.5" />
            </form>
          </>
        ) : (
          <>
            <button onClick={() => setSeed(seed + 1)} className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-0.5 hover:bg-slate-50">
              <Shuffle className="h-3 w-3" aria-hidden />
              换一批
            </button>
            <span className="text-slate-600">从全部 {fmtInt(sample.data?.total)} 行中随机抽 500 行（种子 {seed}，同一种子结果相同）</span>
          </>
        )}
      </div>
      {mode === 'scan' && filters.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {filters.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-800">
              {f.column} {OPS.find((o) => o[0] === f.op)?.[1]} {f.value}
              <button aria-label="移除筛选" onClick={() => { setWindowStart(0); setFilters(filters.filter((_, j) => j !== i)) }}>
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      {mode === 'scan' && blocks.error && <p className="text-xs text-red-600">{blocks.error}</p>}
      {mode === 'scan' && blocks.info && (
        <VirtualTable
          resetToken={resetKey}
          columns={blocks.info.columns}
          count={count}
          getRow={blocks.getRow}
          onRange={onRange}
          sort={sort}
          onSort={onSort}
          scrollToIndex={scrollTo}
          height={560}
        />
      )}
      {mode === 'sample' && sample.error && <p className="text-xs text-red-600">{(sample.error as Error).message}</p>}
      {mode === 'sample' && sample.data && (
        <VirtualTable columns={sample.data.columns} count={sample.data.rows.length} getRow={(i) => sample.data!.rows[i]} height={560} />
      )}
    </div>
  )
}

function FilterBuilder({ columns, onAdd }: { columns: DataColumn[]; onAdd: (f: FilterItem) => void }) {
  const [column, setColumn] = useState<string[]>([])
  const [op, setOp] = useState<Op>('eq')
  const [value, setValue] = useState('')
  const names = useMemo(() => columns.map((c) => c.name), [columns])
  const needsValue = op !== 'is_null' && op !== 'not_null'
  return (
    <form
      className="flex items-center gap-1"
      onSubmit={(e) => {
        e.preventDefault()
        if (!column[0] || (needsValue && value === '')) return
        onAdd({ column: column[0], op, ...(needsValue ? { value } : {}) })
        setValue('')
      }}
    >
      <Filter className="h-3.5 w-3.5 text-slate-400" aria-hidden />
      <ColumnPicker label="筛选列" options={names} value={column} onChange={setColumn} multiple={false} placeholder="筛选列" />
      <select value={op} onChange={(e) => setOp(e.target.value as Op)} aria-label="筛选方式" className="rounded border border-slate-300 bg-white px-1 py-1">
        {OPS.map(([k, label]) => (
          <option key={k} value={k}>
            {label}
          </option>
        ))}
      </select>
      {needsValue && <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="值" aria-label="筛选值" className="w-28 rounded border border-slate-300 px-1.5 py-1" />}
      <button type="submit" className="rounded border border-slate-300 bg-white px-2 py-1 hover:bg-slate-50">
        添加
      </button>
    </form>
  )
}
