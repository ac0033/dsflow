import { useEffect, useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { CheckCircle2, FileCode2, PauseCircle } from 'lucide-react'
import { api } from '../../api'
import MarkdownView, { type MarkdownProps } from '../../components/Markdown'
import NotebookView, { CodeLines, Outputs, foldedLines, join, notebookLang, parseNotebook, type NbCell, type Notebook } from '../../components/NotebookView'
import { Glossary, TermText, useTerms, usedTerms, type TermIndex } from '../../components/Terms'
import { dirname } from '../../lib/paths'
import type { GuideBrief, GuideCell, GuideChecks, GuidePart, GuideView as GuideData, RevisionDetail, StepDetail } from '../../types'
import './guide.css'

/*
 * 讲解 = notebook 导读：左边是 notebook 里真实的单元格与输出，右边是旁注（做什么 / 为什么 / 输出结果讲解）。
 * 内容由执行 agent 写在 guide.yaml 里（docs/agent-guide.md、docs/讲解写法.md），平台只负责渲染、术语提示和数字核对；
 * 还没有导读时，退回到「注册表原话 + notebook 原文 + 术语提示」，并写清该怎么补。
 */

const MARKS = '①②③④⑤⑥⑦⑧⑨'

type Md = Omit<MarkdownProps, 'text'>

function norm(path: string): string {
  const out: string[] = []
  for (const seg of path.split('/')) {
    if (!seg || seg === '.') continue
    if (seg === '..') out.pop()
    else out.push(seg)
  }
  return out.join('/')
}

const indexes = (cell: GuideCell['cell']) => (Array.isArray(cell) ? cell : [cell])

/** 导读里用到的全部 notebook（每格可以覆盖，路径相对本轮目录）。 */
function notebookPaths(v: GuideData | undefined, revDir: string): string[] {
  if (!v) return []
  const out: string[] = []
  const add = (p?: string | null) => {
    if (p && !out.includes(p)) out.push(p)
  }
  add(v.notebook)
  for (const part of v.guide?.parts ?? []) {
    if (part.notebook) add(norm(`${revDir}/${part.notebook}`))
    for (const c of part.cells) if (c.notebook) add(norm(`${revDir}/${c.notebook}`))
  }
  return out
}

function useNotebooks(pid: string, paths: string[]) {
  const results = useQueries({
    queries: paths.map((p) => ({ queryKey: ['file', pid, p], queryFn: () => api.file(pid, p), staleTime: 60_000 })),
  })
  const sizes = results.map((r) => r.data?.content.length ?? 0).join(',')
  const books = useMemo(() => {
    const m = new Map<string, Notebook | null>()
    paths.forEach((p, i) => m.set(p, parseNotebook(results[i]?.data?.content ?? '')))
    return m
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paths.join('|'), sizes])
  return { books, loading: results.some((r) => r.isLoading), error: results.find((r) => r.error)?.error as Error | undefined }
}

export default function GuideView({ pid, root, openFile, d, rev, part, cell, onTab }: {
  pid: string
  root?: string
  openFile: (path: string) => void
  d: StepDetail
  rev: RevisionDetail
  /** 从别处跳回来时要定位到的段落（从 1 数） */
  part?: string | null
  /** 从别处跳回来时要定位到的单元格（notebook 里第几格，从 1 数） */
  cell?: string | null
  onTab: (tab: 'board' | 'code') => void
}) {
  const view = useQuery({ queryKey: ['guide', pid, d.step.id, rev.id], queryFn: () => api.guide(pid, d.step.id, rev.id) })
  const v = view.data
  const terms = useTerms(v?.terms)
  const [showCode, setShowCode] = useState(true)
  const paths = useMemo(() => notebookPaths(v, rev.dir), [v, rev.dir])
  const { books, loading } = useNotebooks(pid, paths)
  const md = { baseDir: v?.notebook ? dirname(v.notebook) : rev.dir, projectId: pid, projectRoot: root, onOpenFile: openFile, terms }
  const g = v?.guide
  const partCount = g?.parts.length ?? 0
  useEffect(() => {
    if (!partCount) return
    // 指名了单元格就落到那一格（答疑、列的说明都从这里跳回来），否则落到那一段
    const target = cell ? document.getElementById(`gcell-${cell}`) : part ? document.getElementById(`gpart-${part}`) : null
    if (!target) return
    target.scrollIntoView({ behavior: 'smooth', block: cell ? 'center' : 'start' })
    if (cell) {
      target.classList.add('is-target')
      const timer = window.setTimeout(() => target.classList.remove('is-target'), 2600)
      return () => window.clearTimeout(timer)
    }
  }, [part, cell, partCount])

  if (view.isLoading) return <p className="text-sm text-slate-500">读取讲解…</p>
  if (view.error) return <p className="text-sm text-red-600">{(view.error as Error).message}</p>
  if (!v) return null

  const text = g ? guideText(g) : ''
  return (
    <div className="guide max-w-5xl">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        {g && v.checks && <Checks checks={v.checks} />}
        {v.notebook && (
          <button onClick={() => openFile(v.notebook!)} className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-slate-600 hover:bg-slate-50" title={v.notebook}>
            <FileCode2 className="h-3.5 w-3.5" aria-hidden />
            {v.notebook.split('/').pop()}
          </button>
        )}
        {g && (
          <label className="ml-auto flex items-center gap-1 text-slate-600">
            <input type="checkbox" checked={showCode} onChange={(e) => setShowCode(e.target.checked)} />
            显示代码
          </label>
        )}
      </div>

      {v.error && <p className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">{v.error}（{v.source}）</p>}

      {g ? (
        <>
          <Brief b={g.brief} terms={terms} />
          {g.parts.length > 1 && <Toc parts={g.parts} />}
          {loading && <p className="mt-3 text-sm text-slate-500">读取 notebook…</p>}
          {g.parts.map((part, pi) => (
            <section key={pi} id={`gpart-${pi + 1}`} className="guide-part">
              <h2>
                <span className="no">{pi + 1}</span>
                <TermText text={part.question} terms={terms} />
              </h2>
              {part.answer && (
                <p className="text-sm leading-relaxed text-slate-800">
                  <TermText text={part.answer} terms={terms} />
                </p>
              )}
              {part.cells.map((note, ci) => (
                <Row
                  key={ci}
                  note={note}
                  nb={books.get(note.notebook ? norm(`${rev.dir}/${note.notebook}`) : part.notebook ? norm(`${rev.dir}/${part.notebook}`) : (v.notebook ?? '')) ?? null}
                  md={md}
                  terms={terms}
                  showCode={showCode}
                  missing={(v.checks?.missing ?? []).filter((m) => m.part === pi && m.cell === ci).map((m) => m.number)}
                />
              ))}
              {part.meaning && (
                <div className="callout co-biz" data-label="业务含义">
                  <p>
                    <TermText text={part.meaning} terms={terms} />
                  </p>
                </div>
              )}
            </section>
          ))}

          <div className="mt-3">
            <Glossary terms={usedTerms(terms, text)} />
          </div>
        </>
      ) : (
        <NoGuide v={v} d={d} rev={rev} md={md} onTab={onTab} />
      )}
    </div>
  )
}

function Toc({ parts }: { parts: GuidePart[] }) {
  return (
    <nav className="guide-toc" aria-label="讲解段落">
      {parts.map((p, i) => (
        <button key={i} type="button" onClick={() => document.getElementById(`gpart-${i + 1}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>
          <span className="no">{i + 1}</span>
          {p.question}
        </button>
      ))}
    </nav>
  )
}

function Checks({ checks }: { checks: GuideChecks }) {
  return (
    <>
      {checks.checked > 0 && (
        <span
          className={`rounded px-1.5 py-0.5 ${checks.found === checks.checked ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-900'}`}
          title="讲解里写的每个数字，平台都回到所引用单元格的代码或输出里找过一遍"
        >
          数字核对 {checks.found}/{checks.checked}
        </span>
      )}
      {checks.errors.length > 0 && (
        <span className="rounded bg-red-100 px-1.5 py-0.5 text-red-800" title={checks.errors.join('\n')}>
          引用有误 {checks.errors.length}
        </span>
      )}
    </>
  )
}

function Continue({ value }: { value: boolean | null }) {
  if (value == null) return null
  return value ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">
      <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
      可以继续
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">
      <PauseCircle className="h-3.5 w-3.5" aria-hidden />
      暂不能继续
    </span>
  )
}

/** 开头六段：背景 / 目的 / 结论 / 操作 / 结果 / 下一步建议。 */
function Brief({ b, terms }: { b: GuideBrief; terms: TermIndex }) {
  const rows: [string, string, boolean][] = [
    ['背景', b.background, false],
    ['目的', b.question, false],
    ['结论', b.answer, true],
    ['操作', b.did, false],
    ['结果', b.result, false],
    ['下一步建议', b.next, false],
  ]
  return (
    <section className="guide-brief">
      <dl>
        {rows.map(([label, text, strong]) =>
          text ? (
            <div key={label} className="line">
              <dt>{label}</dt>
              <dd className={strong ? 'a' : undefined}>
                {strong && <Continue value={b.can_continue} />}
                <TermText text={text} terms={terms} />
              </dd>
            </div>
          ) : null,
        )}
      </dl>
    </section>
  )
}

function Row({ note, nb, md, terms, showCode, missing }: {
  note: GuideCell
  nb: Notebook | null
  md: Md
  terms: TermIndex
  showCode: boolean
  missing: string[]
}) {
  const list = indexes(note.cell)
  const lang = notebookLang(nb)
  const order = new Map<string, number>()
  note.lines.forEach((l, i) => order.set(`${l.cell ?? list[0]}:${l.line}`, i + 1))
  return (
    <div className="guide-row">
      <div className="space-y-2">
        {list.map((i) => {
          const cell = nb?.cells[i - 1]
          if (!cell) return <p key={i} className="text-xs text-amber-700">notebook 里没有第 {i} 个单元格。</p>
          const marks = new Map<number, number>()
          note.lines.forEach((l) => {
            if ((l.cell ?? list[0]) === i) marks.set(l.line, order.get(`${i}:${l.line}`)!)
          })
          return <Cell key={i} at={i} cell={cell} lang={lang} md={md} marks={marks} showCode={showCode} />
        })}
      </div>
      <aside className="guide-note">
        {note.title && <p className="mb-1 text-sm font-semibold text-slate-900">{<TermText text={note.title} terms={terms} />}</p>}
        <dl>
          {note.what && (
            <>
              <dt>做什么</dt>
              <dd>
                <TermText text={note.what} terms={terms} />
              </dd>
            </>
          )}
          {note.why && (
            <>
              <dt>为什么</dt>
              <dd>
                <TermText text={note.why} terms={terms} />
              </dd>
            </>
          )}
          {note.read && (
            <>
              <dt>输出结果讲解</dt>
              <dd>
                <TermText text={note.read} terms={terms} />
              </dd>
            </>
          )}
        </dl>
        {note.lines.length > 0 && (
          <ul className="lines">
            {note.lines.map((l, i) => (
              <li key={i}>
                <span className="mark">{MARKS[Math.min(i, 8)]}</span>
                <span>
                  <TermText text={l.note} terms={terms} />
                </span>
              </li>
            ))}
          </ul>
        )}
        {missing.length > 0 && (
          <p className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs leading-relaxed text-amber-900">
            数字 {missing.join('、')} 在这一格的输出里没有找到。
          </p>
        )}
      </aside>
    </div>
  )
}

function Cell({ at, cell, lang, md, marks, showCode }: {
  at: number
  cell: NbCell
  lang: string
  md: Md
  marks: Map<number, number>
  showCode: boolean
}) {
  if (cell.cell_type === 'markdown')
    return (
      <figure className="guide-cell" id={`gcell-${at}`}>
        <figcaption>单元格 {at} · notebook 里的说明</figcaption>
        <div className="body">
          <MarkdownView text={join(cell.source)} {...md} compact />
        </div>
      </figure>
    )
  const source = join(cell.source)
  const total = source.replace(/\n$/, '').split('\n').length
  // 长代码默认只露出讲到的那几行（行注前后各两行）和开头，其余折起来
  const fold = useMemo(() => foldedLines(total, marks.keys()), [total, marks])
  const [expanded, setExpanded] = useState(false)
  return (
    <figure className="guide-cell" id={`gcell-${at}`}>
      <figcaption>
        单元格 {at} · 代码 {total} 行
        {fold && showCode && (
          <button type="button" className="fold-toggle" onClick={() => setExpanded(!expanded)}>
            {expanded ? '只看讲到的行' : `展开全部 ${total} 行`}
          </button>
        )}
      </figcaption>
      <div className="body">
        {showCode && <CodeLines source={source} lang={lang} marks={marks} visible={expanded ? null : fold} onExpand={() => setExpanded(true)} />}
        <Outputs cell={cell} md={md} />
      </div>
    </figure>
  )
}

function guideText(g: NonNullable<GuideData['guide']>): string {
  const parts = [g.brief.background, g.brief.question, g.brief.answer, g.brief.did, g.brief.result, g.brief.next, ...g.cannot_say]
  for (const p of g.parts) {
    parts.push(p.question, p.answer, p.meaning)
    for (const c of p.cells) parts.push(c.title, c.what, c.why, c.read, ...c.lines.map((l) => l.note))
  }
  return parts.join('\n')
}

/** 还没有讲解：先给这一步登记的目的与结论，再原样显示 notebook（术语照样有提示），并说清该怎么补。 */
function NoGuide({ v, d, rev, md, onTab }: {
  v: GuideData
  d: StepDetail
  rev: RevisionDetail
  md: Md
  onTab: (tab: 'board' | 'code') => void
}) {
  const card = rev.card
  return (
    <>
      <section className="guide-brief is-raw">
        <p className="raw-flag">这一步暂未讲解。下面两段是这一步登记的目的与结论。</p>
        <dl>
          <div className="line">
            <dt>目的</dt>
            <dd>{d.step.op || '这一步还没有写目的。'}</dd>
          </div>
          <div className="line">
            <dt>结论</dt>
            <dd className="a">
              <Continue value={card?.can_continue ?? null} />
              {card?.headline || d.step.finding || '还没有结论。'}
            </dd>
          </div>
        </dl>
      </section>

      <p className="my-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-relaxed text-amber-900">
        补讲解：<code className="rounded bg-white px-1">uv run dsflow guide init 项目目录 {d.step.id} --rev {rev.id}</code> 生成骨架，逐格填「做什么 / 为什么 / 输出结果讲解」，
        再用 <code className="rounded bg-white px-1">dsflow guide put</code> 放回。写法见 docs/讲解写法.md。
      </p>

      {v.notebook ? (
        <NotebookFile pid={md.projectId ?? ''} path={v.notebook} md={md} />
      ) : (
        <p className="rounded-lg border border-dashed border-slate-300 p-6 text-sm leading-relaxed text-slate-600">
          本轮目录里没有 notebook。代码在
          <button onClick={() => onTab('code')} className="mx-1 text-blue-700 underline">代码</button>
          标签，结论在
          <button onClick={() => onTab('board')} className="mx-1 text-blue-700 underline">看板</button>。
        </p>
      )}
    </>
  )
}

function NotebookFile({ pid, path, md }: { pid: string; path: string; md: Md }) {
  const file = useQuery({ queryKey: ['file', pid, path], queryFn: () => api.file(pid, path) })
  if (file.isLoading) return <p className="text-sm text-slate-500">读取 notebook…</p>
  if (file.error) return <p className="text-sm text-red-600">{(file.error as Error).message}</p>
  return file.data ? <NotebookView text={file.data.content} md={md} /> : null
}
