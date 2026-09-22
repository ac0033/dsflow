import { useQuery } from '@tanstack/react-query'
import { Box, FileText, Table2 } from 'lucide-react'
import { api } from '../../api'
import { fmtInt } from '../../lib/format'
import type { RevisionDetail, StepDetail, StepStock, StepTable, StockOther } from '../../types'
import { FilesTree } from './StepFiles'

/**
 * 产物（执行层）：左边进来的表，中间这一步，右边出去的产物；下面是本轮目录里的全部文件。
 * 产物只算有用的最终文件：登记的数据集、说明卡声明了用途的文件、报告、模型。
 */
export default function StepProducts({ pid, d, rev, onOpenTable, openFile }: {
  pid: string
  d: StepDetail
  rev: RevisionDetail
  onOpenTable: (path: string) => void
  openFile: (path: string) => void
}) {
  const stock = useQuery({ queryKey: ['stock', pid, d.step.id, rev.id], queryFn: () => api.stepStock(pid, d.step.id, rev.id), staleTime: 60_000 })
  return (
    <div className="max-w-5xl space-y-4">
      {stock.isLoading && <p className="text-sm text-slate-500">读取…</p>}
      {stock.error && <p className="text-sm text-red-600">{(stock.error as Error).message}</p>}
      {stock.data && <ProductFlow d={d} s={stock.data} onOpenTable={onOpenTable} openFile={openFile} />}
      <section>
        <h3 className="mb-1.5 text-sm font-semibold text-slate-700">
          本轮目录里的全部文件 <span className="font-normal text-slate-400">{rev.files.length}</span>
        </h3>
        <FilesTree files={rev.files} truncated={rev.truncated} onOpen={openFile} />
      </section>
    </div>
  )
}

const ROW = 44
const PAD = 12

type Node = { key: string; label: string; sub?: string; kind: 'table' | 'new' | 'updated' | 'retired' | 'report' | 'model' | 'file'; onClick?: () => void }

function nodesOf(s: StepStock, onOpenTable: (p: string) => void, openFile: (p: string) => void): { left: Node[]; right: Node[] } {
  const shape = (t: StepTable) => (t.ready ? `${fmtInt(t.rows ?? 0)} 行 × ${t.columns} 列` : undefined)
  const parents = new Set([...s.delta.added, ...s.delta.updated].flatMap((t) => t.parents ?? []))
  const inputs = [...s.before.filter((t) => parents.has(t.name)), ...s.delta.checked.filter((t) => !parents.has(t.name))]
  const left: Node[] = inputs.map((t) => ({ key: `in-${t.path}`, label: t.name, sub: shape(t), kind: 'table', onClick: () => onOpenTable(t.path) }))
  const right: Node[] = [
    ...s.delta.added.map((t): Node => ({
      key: `add-${t.path}`, label: t.name,
      sub: t.diff?.known && t.diff.added.length ? `新表 · 新增 ${t.diff.added.length} 列` : shape(t) ? `新表 · ${shape(t)}` : '新表',
      kind: 'new', onClick: () => onOpenTable(t.path),
    })),
    ...s.delta.updated.map((t): Node => ({ key: `upd-${t.path}`, label: t.name, sub: `更新为新版本 ${t.version ?? ''}`, kind: 'updated', onClick: () => onOpenTable(t.path) })),
    ...s.delta.others.map((o: StockOther): Node => ({
      key: `oth-${o.path}`, label: o.rel.split('/').pop() ?? o.rel, sub: o.kind_label === '说明卡声明的产物' ? o.purpose || undefined : o.kind_label,
      kind: o.kind === 'model' || /\.(joblib|pkl|pt|onnx)$/i.test(o.path) ? 'model' : o.kind === 'report' || o.kind === 'acceptance_report' || /\.md$/i.test(o.path) ? 'report' : 'file',
      onClick: () => openFile(o.path),
    })),
    ...s.delta.retired.map((t): Node => ({ key: `ret-${t.path}`, label: t.name, sub: `被 ${t.retired_by} 替代，退出`, kind: 'retired' })),
  ]
  return { left, right }
}

const NODE_STYLE: Record<Node['kind'], string> = {
  table: 'border-slate-300 bg-white text-slate-800',
  new: 'border-blue-500 bg-blue-600 text-white',
  updated: 'border-amber-400 bg-amber-300 text-amber-950',
  retired: 'border-dashed border-slate-300 bg-white text-slate-400 line-through',
  report: 'border-emerald-300 bg-emerald-50 text-emerald-900',
  model: 'border-violet-300 bg-violet-50 text-violet-900',
  file: 'border-slate-200 bg-slate-50 text-slate-700',
}

function NodeBox({ n }: { n: Node }) {
  const Icon = n.kind === 'model' ? Box : n.kind === 'report' || n.kind === 'file' ? FileText : Table2
  const body = (
    <>
      <Icon className="h-3.5 w-3.5 shrink-0 opacity-80" aria-hidden />
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium leading-tight">{n.label}</span>
        {n.sub && <span className="block truncate text-xs leading-tight opacity-80">{n.sub}</span>}
      </span>
    </>
  )
  const cls = `flex h-[36px] w-full items-center gap-2 rounded-lg border px-2.5 text-left ${NODE_STYLE[n.kind]} ${n.onClick ? 'hover:brightness-95' : ''}`
  return n.onClick ? (
    <button type="button" onClick={n.onClick} className={cls} title={n.label}>
      {body}
    </button>
  ) : (
    <div className={cls} title={n.label}>{body}</div>
  )
}

function Links({ count, height, side }: { count: number; height: number; side: 'left' | 'right' }) {
  const mid = height / 2
  const w = 48
  return (
    <svg width={w} height={height} className="shrink-0" aria-hidden>
      {Array.from({ length: count }, (_, i) => {
        const y = PAD + i * ROW + 18
        const [x0, x1] = side === 'left' ? [0, w] : [w, 0]
        const d = side === 'left' ? `M ${x0} ${y} C ${w / 2} ${y}, ${w / 2} ${mid}, ${x1} ${mid}` : `M ${x0} ${mid} C ${w / 2} ${mid}, ${w / 2} ${y}, ${x1} ${y}`
        return <path key={i} d={d} fill="none" stroke="#94a3b8" strokeWidth={1.5} />
      })}
      {count > 0 && <circle cx={side === 'left' ? w : 0} cy={mid} r={3} fill="#2563eb" />}
    </svg>
  )
}

export function ProductFlow({ d, s, onOpenTable, openFile }: { d: StepDetail; s: StepStock; onOpenTable: (p: string) => void; openFile: (p: string) => void }) {
  const { left, right } = nodesOf(s, onOpenTable, openFile)
  if (!left.length && !right.length) return <p className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-600">这一步没有登记任何数据表或产物。</p>
  const rows = Math.max(left.length, right.length, 1)
  const height = PAD * 2 + rows * ROW - (ROW - 36)
  const col = (nodes: Node[]) => (
    <div className="min-w-0 flex-1" style={{ paddingTop: PAD }}>
      {nodes.map((n, i) => (
        <div key={n.key} style={{ marginBottom: i < nodes.length - 1 ? ROW - 36 : 0 }}>
          <NodeBox n={n} />
        </div>
      ))}
    </div>
  )
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-2">
      <div className="flex items-stretch">
        {col(left)}
        <Links count={left.length} height={height} side="left" />
        <div className="flex w-40 shrink-0 items-center" style={{ minHeight: height }}>
          <div className="w-full rounded-lg border-2 border-blue-500 bg-blue-50 px-2 py-2 text-center">
            <span className="block font-mono text-xs text-blue-700">{d.step.id}</span>
            <span className="block text-sm font-semibold text-blue-900">{d.step.title}</span>
          </div>
        </div>
        <Links count={right.length} height={height} side="right" />
        {col(right)}
      </div>
    </div>
  )
}
