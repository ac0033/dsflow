import { Children, isValidElement, useState, type ReactElement, type ReactNode } from 'react'
import Markdown, { defaultUrlTransform, type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { Check, Copy } from 'lucide-react'
import 'katex/dist/katex.min.css'
import { highlight, LANG_LABEL } from '../lib/highlight'
import { resolvePath } from '../lib/paths'
import { rehypeTerms, type TermIndex } from './Terms'
import './markdown.css'

/*
 * 移植自 aitutor 的 RichText：以加粗标签开头的段落（如 **结论**：…）变成 Quarto 式提示块；
 * 代码块带语言标题与复制按钮；报告里的相对链接在平台内打开，不跳出页面。
 */

type Plugins = NonNullable<Parameters<typeof Markdown>[0]['remarkPlugins']>
type MdNode = { type: string; children?: MdNode[]; value?: string; depth?: number; data?: Record<string, unknown> }

const LABELS: Record<string, string> = {
  结论: 'key', 结果: 'key', 小结: 'key', 要点: 'key', 核心数字: 'key', 发现: 'finding',
  操作: 'op', 做法: 'op', 方法: 'op', 例子: 'example', 示例: 'example',
  注意: 'warn', 限制: 'warn', 风险: 'warn', 易错点: 'warn', 业务含义: 'biz', 下一步: 'next',
  补充: 'extra', 依据: 'extra', 证据: 'extra',
}

/** remark-math 只认 $ 定界符；报告里常见的 \( \) 与 \[ \] 先转换。代码不动。 */
export function normalizeMarkdown(text: string): string {
  return text
    .split(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)/)
    .map((part, i) =>
      i % 2
        ? part
        : part
            .replace(/\\\[([\s\S]+?)\\\]/g, (_, m: string) => `\n$$\n${m.trim()}\n$$\n`)
            .replace(/\\\(([\s\S]+?)\\\)/g, (_, m: string) => `$${m.trim()}$`),
    )
    .join('')
}

const textOf = (n: MdNode): string => n.value ?? (n.children || []).map(textOf).join('')

function labelOf(n: MdNode): string | null {
  if (n.type !== 'paragraph' || n.children?.[0]?.type !== 'strong') return null
  const label = textOf(n.children[0]).trim()
  const next = n.children[1]
  return LABELS[label] && (!next || /^\s*[:：]/.test(next.value || '')) ? label : null
}

function unlabel(n: MdNode): MdNode {
  const children = (n.children || []).slice(1)
  if (children[0]?.type === 'text') children[0] = { ...children[0], value: (children[0].value || '').replace(/^\s*[:：]\s*/, '') }
  return { ...n, children }
}

const box = (kind: string, label: string, children: MdNode[]): MdNode => ({
  type: 'callout',
  data: { hName: 'div', hProperties: { className: ['callout', 'co-' + kind], dataLabel: label } },
  children,
})

function remarkCallouts() {
  return (tree: MdNode) => {
    const out: MdNode[] = []
    let open: MdNode | null = null
    let kind = ''
    for (const node of tree.children || []) {
      const label = labelOf(node)
      if (label) {
        kind = LABELS[label]
        open = box(kind, label, [unlabel(node)])
        out.push(open)
        continue
      }
      const joins =
        open &&
        !['heading', 'thematicBreak', 'blockquote'].includes(node.type) &&
        (['code', 'math', 'table', 'list'].includes(node.type) || kind === 'example')
      if (joins) {
        open!.children!.push(node)
        continue
      }
      open = null
      out.push(node)
    }
    tree.children = out
  }
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false)
  const code = Children.toArray(children).find(isValidElement) as ReactElement<{ className?: string; children?: ReactNode }> | undefined
  const lang = /language-([\w+-]+)/.exec(code?.props.className || '')?.[1]?.toLowerCase() || ''
  const raw = Children.toArray(code?.props.children).join('').replace(/\n$/, '')
  const diagram = lang === 'text' || lang === 'plaintext' || (!lang && /[→↓↑←─│┌┐└┘├┤▼▲]/.test(raw))
  return (
    <figure className={'code-block' + (diagram ? ' diagram' : '')}>
      <figcaption>
        <span>{diagram ? '图示' : LANG_LABEL[lang] || lang || '代码'}</span>
        <button
          type="button"
          aria-label="复制代码"
          onClick={() =>
            navigator.clipboard
              ?.writeText(raw)
              .then(() => {
                setCopied(true)
                setTimeout(() => setCopied(false), 1500)
              })
              .catch(() => {})
          }
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? '已复制' : '复制'}
        </button>
      </figcaption>
      <pre className="hljs">
        <code dangerouslySetInnerHTML={{ __html: highlight(raw, diagram ? undefined : lang) }} />
      </pre>
    </figure>
  )
}

export interface MarkdownProps {
  text: string
  /** 报告所在目录（项目内相对路径），用于解析相对链接 */
  baseDir?: string
  projectId?: string
  projectRoot?: string
  onOpenFile?: (path: string) => void
  compact?: boolean
  /** 术语提示：正文里第一次出现的术语加虚线下划线，悬停看白话解释 */
  terms?: TermIndex
}

const plugins = [remarkGfm, remarkMath, remarkCallouts] as unknown as Plugins

export default function MarkdownView({ text, baseDir = '', projectId, projectRoot, onOpenFile, compact, terms }: MarkdownProps) {
  const components: Components = {
    pre: CodeBlock as Components['pre'],
    a: ({ href, children }) => {
      const target = href ? resolvePath(baseDir, href, projectRoot) : null
      if (target && onOpenFile)
        return (
          <a
            href="#"
            className="md-link"
            title={target}
            onClick={(e) => {
              e.preventDefault()
              onOpenFile(target)
            }}
          >
            {children}
          </a>
        )
      if (href && /^https?:/i.test(href))
        return (
          <a href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        )
      return (
        <span className="md-deadlink" title={href ? `${href}（不在项目目录内）` : undefined}>
          {children}
        </span>
      )
    },
    img: ({ src, alt }) => {
      const rel = typeof src === 'string' ? resolvePath(baseDir, src, projectRoot) : null
      const url = rel && projectId ? `/api/projects/${projectId}/file/raw?path=${encodeURIComponent(rel)}` : typeof src === 'string' && /^https?:/i.test(src) ? src : undefined
      return url ? <img src={url} alt={alt ?? ''} loading="lazy" /> : <span className="md-deadlink">[图片：{alt}]</span>
    },
    table: ({ children }) => (
      <div className="md-table">
        <table>{children}</table>
      </div>
    ),
  }
  return (
    <div className={`md-body${compact ? ' md-compact' : ''}`}>
      <Markdown
        remarkPlugins={plugins}
        rehypePlugins={[[rehypeKatex, { strict: false }], ...(terms?.source ? [[rehypeTerms, terms]] : [])] as never}
        components={components}
        urlTransform={(url) => (/^\/?[a-zA-Z]:[\\/]/.test(url) ? url : defaultUrlTransform(url))}
      >
        {normalizeMarkdown(text)}
      </Markdown>
    </div>
  )
}
