import { useMemo } from 'react'
import type { GuideTerm } from '../types'
import './terms.css'

/*
 * 术语提示：讲解与 notebook 说明里出现的行话，第一次出现时标出来，鼠标停上去（或聚焦）看白话解释。
 * 词表来自后端：本步导读登记的 > 项目 vocabulary.json > 平台内置术语表。
 */

export interface TermIndex {
  terms: GuideTerm[]
  byName: Map<string, GuideTerm>
  source: string
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const ASCII = /^[\x20-\x7e]+$/

export function buildTerms(terms: GuideTerm[] | undefined): TermIndex {
  const byName = new Map<string, GuideTerm>()
  for (const t of terms ?? [])
    for (const name of [t.term, ...(t.aliases ?? [])]) if (name && !byName.has(name)) byName.set(name, t)
  // 长词优先，避免"训练集"被"训练"截断；英文词要求前后不是字母数字，"lag1" 里不会认出 "lag"
  const parts = [...byName.keys()]
    .sort((a, b) => b.length - a.length)
    .map((n) => (ASCII.test(n) ? `(?<![A-Za-z0-9_])${escape(n)}(?![A-Za-z0-9_])` : escape(n)))
  return { terms: terms ?? [], byName, source: parts.join('|') }
}

export const EMPTY_TERMS: TermIndex = { terms: [], byName: new Map(), source: '' }

export function useTerms(terms: GuideTerm[] | undefined): TermIndex {
  return useMemo(() => buildTerms(terms), [terms])
}

interface Piece {
  text: string
  term?: GuideTerm
}

/** 把一段文字切成「普通文字 / 术语」；同一个 seen 里每个术语只标第一次。 */
export function splitTerms(text: string, index: TermIndex, seen: Set<string>): Piece[] {
  if (!index.source || !text) return [{ text }]
  const re = new RegExp(index.source, 'g')
  const out: Piece[] = []
  let at = 0
  for (let m = re.exec(text); m; m = re.exec(text)) {
    const term = index.byName.get(m[0])
    if (!term || seen.has(term.term)) continue
    seen.add(term.term)
    if (m.index > at) out.push({ text: text.slice(at, m.index) })
    out.push({ text: m[0], term })
    at = m.index + m[0].length
  }
  if (at < text.length) out.push({ text: text.slice(at) })
  return out
}

/** 一段纯文字，术语加虚线下划线。 */
export function TermText({ text, terms, seen }: { text: string; terms: TermIndex; seen?: Set<string> }) {
  const pieces = useMemo(() => splitTerms(text, terms, seen ?? new Set()), [text, terms, seen])
  return (
    <>
      {pieces.map((p, i) =>
        p.term ? (
          <span key={i} className="term" tabIndex={0} data-term={p.term.term} data-plain={p.term.plain}>
            {p.text}
          </span>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  )
}

type HastNode = { type: string; tagName?: string; value?: string; children?: HastNode[]; properties?: Record<string, unknown> }
const SKIP = new Set(['code', 'pre', 'a', 'script', 'style'])

/** markdown / notebook 说明单元格里的术语提示（代码、链接里不动）。 */
export function rehypeTerms(index: TermIndex) {
  return (tree: HastNode) => {
    if (!index.source) return
    const seen = new Set<string>()
    const walk = (node: HastNode) => {
      if (!node.children) return
      const out: HastNode[] = []
      for (const child of node.children) {
        if (child.type === 'text' && !SKIP.has(node.tagName ?? '')) {
          for (const piece of splitTerms(child.value ?? '', index, seen))
            out.push(
              piece.term
                ? {
                    type: 'element',
                    tagName: 'span',
                    properties: { className: ['term'], tabIndex: 0, dataTerm: piece.term.term, dataPlain: piece.term.plain },
                    children: [{ type: 'text', value: piece.text }],
                  }
                : { type: 'text', value: piece.text },
            )
        } else {
          walk(child)
          out.push(child)
        }
      }
      node.children = out
    }
    walk(tree)
  }
}

/** 本步用到的术语：在这些文字里真的出现过的才列出来。 */
export function usedTerms(index: TermIndex, text: string): GuideTerm[] {
  const seen = new Set<string>()
  splitTerms(text, index, seen)
  return index.terms.filter((t) => seen.has(t.term))
}

export function Glossary({ terms }: { terms: GuideTerm[] }) {
  if (!terms.length) return null
  return (
    <details className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <summary className="cursor-pointer text-sm font-medium text-slate-700">本步出现的术语（{terms.length} 个）</summary>
      <dl className="mt-2 grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[10rem_1fr]">
        {terms.map((t) => (
          <div key={t.term} className="contents">
            <dt className="font-medium text-slate-800">
              {t.term}
              {t.source && t.source !== '内置' && <span className="ml-1 text-[11px] font-normal text-slate-400">{t.source}</span>}
            </dt>
            <dd className="text-slate-600">{t.plain}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}
