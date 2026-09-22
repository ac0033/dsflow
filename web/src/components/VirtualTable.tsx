import { useEffect, useMemo, useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { fmtCell } from '../lib/format'
import type { Cell, DataColumn } from '../types'

const ROW_H = 28
const HEADER_H = 34
const ROWNUM_W = 76
const KIND_TAG: Record<string, string> = { numeric: '数', temporal: '时', text: '文', boolean: '布', other: '其' }

function colWidth(c: DataColumn): number {
  const byName = 28 + [...c.name].reduce((w, ch) => w + (ch.charCodeAt(0) > 255 ? 13 : 7.5), 0)
  const byKind = c.kind === 'text' ? 170 : c.kind === 'temporal' ? 150 : 100
  return Math.round(Math.min(280, Math.max(byName, byKind)))
}

interface Props {
  columns: DataColumn[]
  count: number
  getRow: (i: number) => Cell[] | undefined
  onRange?: (start: number, end: number) => void
  sort?: { column: string; desc: boolean } | null
  onSort?: (column: string) => void
  height?: number
  rowLabel?: (i: number, row: Cell[] | undefined) => string
  scrollToIndex?: number | null
  /** 这个值变了（换排序、筛选、分段）就回到顶部，但保留横向位置，刚排序的列不会跑出视野 */
  resetToken?: string
  /** 第一列表头：数据文件里是"原始行号"（能回溯到原记录）；SQL 结果只是"序号" */
  rowHeader?: string
  /** 要点亮的列名（本步新增的列），表头加角标、整列换底色 */
  highlight?: Set<string>
  highlightLabel?: string
  /** 原来就有、但这一步把值改了的列 */
  changed?: Set<string>
  changedLabel?: string
}

/** 行列双向虚拟滚动：只渲染可视区的单元格；第一列是原始行号（文件中的第几行）。 */
export default function VirtualTable({ columns, count, getRow, onRange, sort, onSort, height = 520, rowLabel, scrollToIndex, resetToken, rowHeader = '原始行号', highlight, highlightLabel = '本步新增', changed, changedLabel = '本步改了值' }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const widths = useMemo(() => columns.map(colWidth), [columns])
  const rows = useVirtualizer({ count, getScrollElement: () => scrollRef.current, estimateSize: () => ROW_H, overscan: 12 })
  const cols = useVirtualizer({
    horizontal: true,
    count: columns.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => widths[i],
    overscan: 3,
  })
  useEffect(() => cols.measure(), [widths, cols])
  useEffect(() => {
    if (scrollToIndex != null && scrollToIndex < count) rows.scrollToIndex(scrollToIndex, { align: 'start' })
  }, [scrollToIndex, count, rows])
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0
  }, [resetToken])

  const items = rows.getVirtualItems()
  const first = items[0]?.index
  const last = items[items.length - 1]?.index
  useEffect(() => {
    if (first != null && last != null) onRange?.(first, last)
  }, [first, last, onRange])

  const vcols = cols.getVirtualItems()
  const innerW = cols.getTotalSize()

  return (
    <div
      ref={scrollRef}
      className="relative overflow-auto rounded-md border border-slate-200 bg-white text-[12px]"
      style={{ height }}
      role="grid"
      aria-rowcount={count}
      aria-colcount={columns.length}
    >
      <div style={{ width: innerW + ROWNUM_W, height: rows.getTotalSize() + HEADER_H, position: 'relative' }}>
        <div className="sticky top-0 z-20 flex border-b border-slate-200 bg-slate-50" style={{ height: HEADER_H, width: innerW + ROWNUM_W }} role="row">
          <div className="sticky left-0 z-30 flex items-center border-r border-slate-200 bg-slate-50 px-2 text-[11px] text-slate-500" style={{ width: ROWNUM_W }}>
            {rowHeader}
          </div>
          <div className="relative" style={{ width: innerW }}>
            {vcols.map((vc) => {
              const c = columns[vc.index]
              const active = sort?.column === c.name
              const lit = highlight?.has(c.name)
              const chg = !lit && changed?.has(c.name)
              return (
                <button
                  key={vc.key}
                  type="button"
                  role="columnheader"
                  aria-sort={active ? (sort!.desc ? 'descending' : 'ascending') : 'none'}
                  onClick={() => onSort?.(c.name)}
                  disabled={!onSort}
                  title={`${c.name}（${c.type}）${lit ? `，${highlightLabel}` : chg ? `，${changedLabel}` : ''}${onSort ? '，点击排序' : ''}`}
                  className={`absolute top-0 flex h-full items-center gap-1 truncate border-r px-2 text-left font-medium disabled:hover:bg-transparent ${lit ? 'border-amber-300 bg-amber-100 text-amber-900 hover:bg-amber-200' : chg ? 'border-sky-300 bg-sky-100 text-sky-900 hover:bg-sky-200' : 'border-slate-200 hover:bg-slate-100'}`}
                  style={{ left: vc.start, width: vc.size }}
                >
                  <span className={`shrink-0 rounded px-1 text-[10px] font-normal ${lit ? 'bg-amber-200 text-amber-900' : chg ? 'bg-sky-200 text-sky-900' : 'bg-slate-200 text-slate-600'}`}>{lit ? '新' : chg ? '变' : (KIND_TAG[c.kind] ?? '其')}</span>
                  <span className="truncate">{c.name}</span>
                  {active && (sort!.desc ? <ArrowDown className="h-3 w-3 shrink-0" /> : <ArrowUp className="h-3 w-3 shrink-0" />)}
                </button>
              )
            })}
          </div>
        </div>
        {items.map((vr) => {
          const row = getRow(vr.index)
          return (
            <div
              key={vr.key}
              role="row"
              className={`absolute left-0 flex ${vr.index % 2 ? 'bg-slate-50/50' : ''}`}
              style={{ top: vr.start + HEADER_H, height: ROW_H, width: innerW + ROWNUM_W }}
            >
              <div className="tabular sticky left-0 z-10 flex items-center border-r border-slate-200 bg-inherit bg-white px-2 text-[11px] text-slate-500" style={{ width: ROWNUM_W }}>
                {rowLabel ? rowLabel(vr.index, row) : row?.[0] != null ? String(Number(row[0]) + 1) : ''}
              </div>
              <div className="relative" style={{ width: innerW }}>
                {vcols.map((vc) => {
                  const kind = columns[vc.index].kind
                  const v = row?.[vc.index + 1]
                  const lit = highlight?.has(columns[vc.index].name)
                  const chg = !lit && changed?.has(columns[vc.index].name)
                  return (
                    <div
                      key={vc.key}
                      role="gridcell"
                      className={`absolute top-0 flex h-full items-center truncate border-r border-slate-100 px-2 ${kind === 'numeric' ? 'tabular justify-end' : ''} ${lit ? 'bg-amber-50' : chg ? 'bg-sky-50' : ''}`}
                      style={{ left: vc.start, width: vc.size }}
                      title={v != null ? fmtCell(v) : undefined}
                    >
                      {row === undefined ? (
                        <span className="h-2 w-2/3 rounded bg-slate-100" />
                      ) : v === null ? (
                        <span className="text-[11px] italic text-slate-400">空</span>
                      ) : v === '' ? (
                        <span className="text-[11px] text-slate-400">""</span>
                      ) : (
                        <span className="truncate">{fmtCell(v as Cell)}</span>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
