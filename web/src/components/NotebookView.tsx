import { useMemo, useState } from 'react'
import DOMPurify from 'dompurify'
import { highlight } from '../lib/highlight'
import MarkdownView, { type MarkdownProps } from './Markdown'

export interface NbOutput {
  output_type: string
  name?: string
  text?: string | string[]
  data?: Record<string, string | string[]>
  ename?: string
  evalue?: string
  traceback?: string[]
}
export interface NbCell {
  cell_type: string
  source: string | string[]
  outputs?: NbOutput[]
  execution_count?: number | null
}
export interface Notebook {
  cells: NbCell[]
  metadata?: { kernelspec?: { display_name?: string; language?: string }; language_info?: { name?: string } }
}

export const join = (s?: string | string[]) => (Array.isArray(s) ? s.join('') : (s ?? ''))
// eslint-disable-next-line no-control-regex
const ANSI = /\x1b\[[0-9;]*[A-Za-z]/g

export function parseNotebook(text: string): Notebook | null {
  try {
    const nb = JSON.parse(text) as Notebook
    return Array.isArray(nb?.cells) ? nb : null
  } catch {
    return null
  }
}

export const notebookLang = (nb: Notebook | null) =>
  nb?.metadata?.language_info?.name ?? nb?.metadata?.kernelspec?.language ?? 'python'

/** 代码：左边行号；marks 里的行改成 ①②③，与右边的行注对应。给了 onPick 就能点，点了旁边的数据视图跟着亮。 */
/** 折叠后要显示的行：有行注的行前后各留两行，再加开头三行定位；没有行注就只看开头。 */
export function foldedLines(total: number, marked: Iterable<number>, minLines = 14): Set<number> | null {
  if (total <= minLines) return null
  const keep = new Set<number>()
  const marks = [...marked]
  for (let i = 1; i <= Math.min(3, total); i++) keep.add(i)
  if (!marks.length) for (let i = 1; i <= Math.min(10, total); i++) keep.add(i)
  for (const m of marks) for (let i = Math.max(1, m - 2); i <= Math.min(total, m + 2); i++) keep.add(i)
  return keep.size < total ? keep : null
}

export function CodeLines({ source, lang, marks, picked, onPick, visible, onExpand }: {
  source: string
  lang: string
  marks?: Map<number, number>
  picked?: number | null
  onPick?: (line: number | null) => void
  /** 只显示这些行（其余折成一行「省略 n 行」）；null 或不传就全显示 */
  visible?: Set<number> | null
  onExpand?: () => void
}) {
  const lines = source.replace(/\n$/, '').split('\n')
  const folded = !!visible && visible.size < lines.length
  const segments: { from: number; to: number; hidden: boolean }[] = []
  if (folded) {
    let i = 1
    while (i <= lines.length) {
      const hidden = !visible!.has(i)
      let j = i
      while (j < lines.length && !visible!.has(j + 1) === hidden) j++
      segments.push({ from: i, to: j, hidden })
      i = j + 1
    }
  } else segments.push({ from: 1, to: lines.length, hidden: false })

  const html = segments
    .map((s) =>
      s.hidden
        ? `<span class="fold-gap" role="button" tabindex="0">⋯ 省略 ${s.to - s.from + 1} 行，点开看全部</span>`
        : highlight(lines.slice(s.from - 1, s.to).join('\n'), lang),
    )
    .join('\n')
  const expand = (e: { target: EventTarget | null }) => {
    if ((e.target as HTMLElement | null)?.classList?.contains('fold-gap')) onExpand?.()
  }
  return (
    <div className="nb-code">
      <div className="gutter">
        {segments.map((s) =>
          s.hidden ? (
            <button key={`gap-${s.from}`} type="button" className="fold" onClick={onExpand} title={`展开第 ${s.from}–${s.to} 行`}>
              ⋯
            </button>
          ) : (
            lines.slice(s.from - 1, s.to).map((_, k) => {
              const at = s.from + k
              const order = marks?.get(at)
              if (order == null) return <span key={at}>{at}</span>
              const label = '①②③④⑤⑥⑦⑧⑨'[Math.min(order - 1, 8)]
              return onPick ? (
                <button
                  key={at}
                  type="button"
                  className={`on pick${picked === at ? ' picked' : ''}`}
                  aria-pressed={picked === at}
                  title={picked === at ? '收起这一行的数据变化' : '看这一行在数据上做了什么'}
                  onClick={() => onPick(picked === at ? null : at)}
                >
                  {label}
                </button>
              ) : (
                <span key={at} className="on">
                  {label}
                </span>
              )
            })
          ),
        )}
      </div>
      <pre className="hljs" onClick={expand} onKeyDown={(e) => e.key === 'Enter' && expand(e)}>
        <code dangerouslySetInnerHTML={{ __html: html }} />
      </pre>
    </div>
  )
}

export function OutputView({ o, md }: { o: NbOutput; md: Omit<MarkdownProps, 'text'> }) {
  if (o.output_type === 'stream')
    return <pre className={`nb-out${o.name === 'stderr' ? ' nb-stderr' : ''}`}>{join(o.text).replace(ANSI, '')}</pre>
  if (o.output_type === 'error')
    return (
      <pre className="nb-out nb-error">
        {`${o.ename}: ${o.evalue}\n`}
        {(o.traceback ?? []).join('\n').replace(ANSI, '')}
      </pre>
    )
  const d = o.data ?? {}
  if (d['image/png']) return <img className="mt-1 max-w-full" src={`data:image/png;base64,${join(d['image/png']).replace(/\s/g, '')}`} alt="输出图像" />
  if (d['image/svg+xml']) return <img className="mt-1 max-w-full" src={`data:image/svg+xml;utf8,${encodeURIComponent(join(d['image/svg+xml']))}`} alt="输出图像" />
  if (d['text/html']) return <div className="nb-html overflow-x-auto" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(join(d['text/html'])) }} />
  if (d['text/markdown']) return <MarkdownView text={join(d['text/markdown'])} {...md} compact />
  if (d['text/plain']) return <pre className="nb-out">{join(d['text/plain'])}</pre>
  return null
}

export function Outputs({ cell, md }: { cell: NbCell; md: Omit<MarkdownProps, 'text'> }) {
  const outputs = cell.outputs ?? []
  if (!outputs.length) return <p className="mt-1 text-xs text-slate-400">这一格没有输出。</p>
  return (
    <>
      {outputs.map((o, i) => (
        <OutputView key={i} o={o} md={md} />
      ))}
    </>
  )
}

/** notebook：先说执行情况（执行了几个单元、有没有报错），再按 Quarto 的方式让代码与输出相邻。 */
export default function NotebookView({ text, md }: { text: string; md: Omit<MarkdownProps, 'text'> }) {
  const [fold, setFold] = useState(false)
  const nb = useMemo(() => parseNotebook(text), [text])
  if (!nb) return <p className="text-sm text-red-600">这个 notebook 不是合法的 JSON，无法显示。</p>

  const code = nb.cells.filter((c) => c.cell_type === 'code')
  const executed = code.filter((c) => c.execution_count != null).length
  const errors = code.filter((c) => c.outputs?.some((o) => o.output_type === 'error')).length
  const lang = notebookLang(nb)

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-3 rounded-md bg-slate-50 px-3 py-2 text-xs">
        <span>
          共 {nb.cells.length} 个单元，其中代码 {code.length} 个：已执行 {executed} 个
          {errors ? <b className="text-red-700">，{errors} 个有错误输出</b> : '，没有错误输出'}
          {executed < code.length && <span className="text-amber-700">（{code.length - executed} 个没有执行记录）</span>}。
        </span>
        <label className="ml-auto flex items-center gap-1">
          <input type="checkbox" checked={fold} onChange={(e) => setFold(e.target.checked)} />
          折叠代码，只看输出
        </label>
      </div>
      {nb.cells.map((c, i) =>
        c.cell_type === 'markdown' ? (
          <div key={i} className="nb-cell pl-[60px]">
            <MarkdownView text={join(c.source)} {...md} compact />
          </div>
        ) : c.cell_type === 'code' ? (
          <div key={i} className="nb-cell nb-in">
            <div className="nb-prompt">[{c.execution_count ?? ' '}]</div>
            <div className="nb-body">
              <details open={!fold} className="code-block">
                <summary className="cursor-pointer px-2 py-0.5 text-[11px] text-slate-500">代码（{join(c.source).split('\n').length} 行）</summary>
                <pre className="code-view hljs">
                  <code dangerouslySetInnerHTML={{ __html: highlight(join(c.source), lang) }} />
                </pre>
              </details>
              {c.outputs?.map((o, j) => (
                <OutputView key={j} o={o} md={md} />
              ))}
            </div>
          </div>
        ) : null,
      )}
    </div>
  )
}
