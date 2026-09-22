import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { Database, X } from 'lucide-react'
import { api } from '../api'
import { fmtBytes } from '../lib/format'
import { highlight, langForPath } from '../lib/highlight'
import { DATA_RE, IMAGE_RE, dirname } from '../lib/paths'
import MarkdownView from './Markdown'
import NotebookView from './NotebookView'
import { EMPTY_TERMS, Glossary, usedTerms, type TermIndex } from './Terms'

interface Props {
  pid: string
  path: string
  projectRoot?: string
  onOpenFile: (path: string) => void
  onClose?: () => void
  /** 术语提示：文里的行话加虚线下划线、悬停看白话解释，文末列出本篇出现过的术语 */
  terms?: TermIndex
}

/** 项目内任意文件的阅读器：md / qmd / ipynb / 代码 / json / 图片 / html；数据文件转到数据视图。 */
export default function FileViewer({ pid, path, projectRoot, onOpenFile, onClose, terms }: Props) {
  const isImage = IMAGE_RE.test(path)
  const isData = DATA_RE.test(path)
  const file = useQuery({ queryKey: ['file', pid, path], queryFn: () => api.file(pid, path), enabled: !isImage && !isData })
  const md = { baseDir: dirname(path), projectId: pid, projectRoot, onOpenFile, terms }
  const suffix = path.slice(path.lastIndexOf('.')).toLowerCase()

  return (
    <article className="min-w-0 rounded-lg border border-slate-200 bg-white">
      <header className="flex items-center gap-2 border-b border-slate-200 px-3 py-2 text-xs">
        <span className="min-w-0 flex-1 truncate font-mono text-slate-600" title={path}>
          {path}
        </span>
        {file.data && <span className="shrink-0 text-slate-400">{fmtBytes(file.data.size)}</span>}
        {isData && (
          <Link to={`/p/${pid}/data?tab=files&path=${encodeURIComponent(path)}`} className="inline-flex shrink-0 items-center gap-1 rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50">
            <Database className="h-3 w-3" aria-hidden />
            在数据视图打开
          </Link>
        )}
        {onClose && (
          <button onClick={onClose} aria-label="关闭文件" className="shrink-0 rounded p-0.5 text-slate-500 hover:bg-slate-100">
            <X className="h-4 w-4" />
          </button>
        )}
      </header>
      <div className="p-4">
        {isImage && <img src={`/api/projects/${pid}/file/raw?path=${encodeURIComponent(path)}`} alt={path} className="max-w-full" />}
        {isData && <p className="text-sm text-slate-600">这是数据文件。在数据视图里可以翻页浏览、看画像、和其他版本对比。</p>}
        {file.isLoading && <p className="text-sm text-slate-500">读取中…</p>}
        {file.error && <p className="text-sm text-red-600">{(file.error as Error).message}</p>}
        {file.data && <Body suffix={suffix} path={path} content={file.data.content} md={md} terms={terms ?? EMPTY_TERMS} />}
      </div>
    </article>
  )
}

function Body({ suffix, path, content, md, terms }: {
  suffix: string
  path: string
  content: string
  md: Parameters<typeof MarkdownView>[0] extends infer P ? Omit<P, 'text'> : never
  terms: TermIndex
}) {
  // 这一篇里真的出现过的术语列在文末：执行计划、报告这些没有讲解的文档靠它解释行话
  const glossary = terms.source ? <Glossary terms={usedTerms(terms, content)} /> : null
  if (suffix === '.md')
    return (
      <>
        <MarkdownView text={content} {...md} />
        {glossary}
      </>
    )
  if (suffix === '.qmd')
    return (
      <>
        <p className="mb-3 rounded bg-amber-50 px-2 py-1.5 text-xs text-amber-900">Quarto 源文件：本机没有安装 Quarto，代码块没有执行、也没有渲染，下面按 Markdown 显示源内容。</p>
        <MarkdownView text={content.replace(/^---\n[\s\S]*?\n---\n/, '')} {...md} />
        {glossary}
      </>
    )
  if (suffix === '.ipynb')
    return (
      <>
        <NotebookView text={content} md={md} />
        {glossary}
      </>
    )
  if (suffix === '.html')
    return (
      <>
        <p className="mb-2 text-xs text-slate-500">静态显示 HTML（已禁止脚本运行）。</p>
        <iframe title={path} sandbox="" srcDoc={content} className="h-[70vh] w-full rounded border border-slate-200" />
      </>
    )
  let text = content
  let lang = langForPath(path)
  if (suffix === '.json' && content.length < 2_000_000) {
    try {
      text = JSON.stringify(JSON.parse(content), null, 2)
    } catch {
      lang = undefined
    }
  }
  return (
    <pre className="code-view hljs max-h-[75vh] overflow-auto rounded border border-slate-100">
      <code dangerouslySetInnerHTML={{ __html: highlight(text, lang) }} />
    </pre>
  )
}
