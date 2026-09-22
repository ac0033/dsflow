import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookmarkPlus, BookOpen, FileCode2, Highlighter, Loader2, MessageCircleQuestion, Send, Settings2, Table2, Trash2, Wrench, X } from 'lucide-react'
import { api, askStream, type AskBody } from '../../api'
import MarkdownView from '../Markdown'
import { useTerms } from '../Terms'
import type { AskLink, AskRecord } from '../../types'
import { useAsk } from './AskContext'
import ModelSetup from './ModelSetup'
import { applyMarks, ASKED, clearMarks, hitTest, NOTED, type Marked } from './marks'
import './ask.css'

/*
 * 答疑对话框：右侧抽屉，问的是"我现在看的这一屏"。
 *
 * 上下文由后端组装：当前步骤与轮次、这一屏的原文、选中的那句话、已登记的术语；模型只有只读工具，改不了项目。
 * 答案里的数字后端会回到上下文和工具返回里核对一遍，找不到出处的会在答案下面列出来。
 */

/** 选项卡的中文名，和页面上的标签一致（后端组装上下文时也用同一套说法）。 */
const TAB_LABEL: Record<string, string> = {
  guide: '讲解', board: '看板', data: '数据', plan: '执行计划', code: '代码', log: '执行日志', products: '产物',
  flow: '流程图', tracker: '问题与决策', runs: '运行与实验', models: '模型与交付', overview: '总览',
}
const fmt = (at: number) => new Date(at * 1000).toLocaleString('zh-CN', { hour12: false }).slice(5, -3)
/** 取答案的第一句话，用作登记术语时的白话解释初值。 */
const firstSentence = (text: string) => (text.replace(/[#*`>]/g, '').split(/[。！？\n]/).find((s) => s.trim().length > 4) ?? '').trim()

export default function AskDock() {
  const ask = useAsk()
  const client = useQueryClient()
  const { pid = '', scope = {}, open = false, draft = null, focus = null, notes = [] } = ask ?? {}
  const step = scope.step ?? null
  const rev = scope.rev ?? null

  const status = useQuery({ queryKey: ['askStatus'], queryFn: api.askStatus, staleTime: 30_000 })
  const asks = useQuery({ queryKey: ['asks', pid, step], queryFn: () => api.asks(pid, step), enabled: Boolean(pid) })
  const termList = useQuery({ queryKey: ['terms', pid, step, rev], queryFn: () => api.terms(pid, step, rev), enabled: Boolean(pid), staleTime: 60_000 })
  const terms = useTerms(termList.data?.terms)

  const records = useMemo(() => asks.data?.records ?? [], [asks.data])
  const [question, setQuestion] = useState('')
  const [useTools, setUseTools] = useState(true)
  const [live, setLive] = useState<{ question: string; quote: string; notes: { quote: string; note: string }[]; text: string; tools: string[]; error: string } | null>(null)
  const [quote, setQuote] = useState('')
  const [setup, setSetup] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const marks = useRef<Marked[]>([])

  // 还没有可用的模型时，配置表单自动展开；配好以后由用户点「开始提问」收起
  useEffect(() => {
    if (status.data && !status.data.ready) setSetup(true)
  }, [status.data])

  // 选中文字后点「问 AI」：把引文接过来，光标落到输入框
  const input = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    if (!draft) return
    setQuote(draft.quote)
    ask?.clearDraft()
    window.setTimeout(() => input.current?.focus(), 50)
  }, [draft, ask])

  // 钉住的引文在页面上高亮；内容换了（切选项卡、数据读完）重新找一次位置
  useEffect(() => {
    const here = (tab: string) => !tab || !scope.tab || tab === scope.tab
    const pinned = records
      .filter((r) => r.mark && here(r.tab))
      .flatMap((r) => [r.quote, ...(r.notes ?? []).map((n) => n.quote)].filter(Boolean).map((quote) => ({ id: r.id, quote })))
    const root = () => document.querySelector('[data-ask-root]') as HTMLElement | null
    const paint = () => {
      marks.current = applyMarks(root(), pinned, ASKED)
    }
    const timer = window.setTimeout(paint, 80)
    const host = root()
    const observer = host ? new MutationObserver(() => window.setTimeout(paint, 80)) : null
    observer?.observe(host!, { childList: true, subtree: true, characterData: true })
    return () => {
      window.clearTimeout(timer)
      observer?.disconnect()
      clearMarks()
    }
  }, [records, scope.tab, scope.step, scope.rev])

  // 还没发出去的标注：在标它的那一页上画成蓝色，发出去之后改由上面那段按问答来画
  useEffect(() => {
    const here = notes.filter((n) => (!n.step || !scope.step || n.step === scope.step) && (!n.tab || !scope.tab || n.tab === scope.tab))
    const root = () => document.querySelector('[data-ask-root]') as HTMLElement | null
    const paint = () => applyMarks(root(), here.map((n) => ({ id: n.id, quote: n.quote })), NOTED)
    const timer = window.setTimeout(paint, 80)
    const host = root()
    const observer = host ? new MutationObserver(() => window.setTimeout(paint, 80)) : null
    observer?.observe(host!, { childList: true, subtree: true, characterData: true })
    return () => {
      window.clearTimeout(timer)
      observer?.disconnect()
      clearMarks(NOTED)
    }
  }, [notes, scope.tab, scope.step, scope.rev])

  // 点高亮的那句话 → 打开对话框并定位到那条问答
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const id = hitTest(marks.current, e.clientX, e.clientY)
      if (id) ask?.setFocus(id)
    }
    document.addEventListener('click', onClick)
    return () => document.removeEventListener('click', onClick)
  }, [ask])

  useEffect(() => {
    if (!open) return
    const target = focus ? document.getElementById(`ask-${focus}`) : box.current?.lastElementChild
    target?.scrollIntoView({ behavior: 'smooth', block: focus ? 'center' : 'end' })
  }, [open, focus, records.length, live?.text])

  const send = async () => {
    const text = question.trim()
    if (!text || live) return
    const history = records.slice(-3).map((r) => ({ question: r.question, answer: r.answer }))
    const sending = notes.map((n) => ({ quote: n.quote, note: n.note }))
    const body: AskBody = { question: text, step, rev, tab: scope.tab, file: scope.file, quote, notes: sending, tools: useTools, history }
    setLive({ question: text, quote, notes: sending, text: '', tools: [], error: '' })
    setQuestion('')
    setQuote('')
    ask?.clearNotes()
    try {
      await askStream(pid, body, (event) => {
        if (event.type === 'text') setLive((l) => (l ? { ...l, text: l.text + event.delta } : l))
        else if (event.type === 'tool') setLive((l) => (l ? { ...l, tools: [...l.tools, event.name] } : l))
        else if (event.type === 'error') setLive((l) => (l ? { ...l, error: event.message } : l))
      })
    } catch (e) {
      setLive((l) => (l ? { ...l, error: (e as Error).message } : l))
      await new Promise((r) => window.setTimeout(r, 2500))
    }
    setLive(null)
    client.invalidateQueries({ queryKey: ['asks', pid, step] })
  }

  if (!ask) return null
  if (!open)
    return (
      <button type="button" className="ask-fab" onClick={() => ask.ask()} title="答疑：选中页面上的任何一句话也能直接问">
        <MessageCircleQuestion className="h-5 w-5" aria-hidden />
        <span>答疑</span>
        {notes.length > 0 && <span className="ask-fab-note">{notes.length} 处待问</span>}
        {records.length > 0 && <span className="ask-fab-n">{records.length}</span>}
      </button>
    )

  const ready = status.data?.ready
  return (
    <aside className="ask-dock" aria-label="答疑对话框">
      <header>
        <MessageCircleQuestion className="h-4 w-4 text-blue-700" aria-hidden />
        <span className="font-medium">答疑</span>
        <span className="ask-where">{step ? `${step}${scope.tab ? ` · ${TAB_LABEL[scope.tab] ?? scope.tab}` : ''}` : '项目层'}</span>
        <button type="button" className="ask-model" onClick={() => setSetup(!setup)} title={ready ? `正在用 ${status.data?.model_id}，点一下换模型` : '点一下配置模型'}>
          <Settings2 className="h-3 w-3" aria-hidden />
          {status.data?.model ?? '未配置模型'}
        </button>
        <button type="button" onClick={ask.close} aria-label="关闭答疑" className="ml-auto rounded p-0.5 hover:bg-slate-100">
          <X className="h-4 w-4" />
        </button>
      </header>

      {setup && <ModelSetup onDone={() => setSetup(false)} />}

      <div className="ask-list" ref={box}>
        {!records.length && !live && (
          <p className="ask-empty">
            在页面上选中一句看不懂的话，点「问 AI」马上问；点「标注」先写一句备注留在页面上，标完几处再写一个问题一起发。答案里的数字平台会回到原文里核对一遍。
          </p>
        )}
        {records.map((r) => (
          <RecordCard key={r.id} pid={pid} r={r} terms={terms} focused={r.id === focus} onChanged={() => client.invalidateQueries({ queryKey: ['asks', pid, step] })} />
        ))}
        {live && (
          <article className="ask-card">
            {live.quote && <blockquote className="ask-quote">{live.quote}</blockquote>}
            <NoteList notes={live.notes} />
            <p className="ask-q">{live.question}</p>
            {live.tools.map((t, i) => (
              <p key={i} className="ask-tool">
                <Wrench className="h-3 w-3" aria-hidden />
                正在查：{t}
              </p>
            ))}
            {live.text ? (
              <div className="ask-a" data-ask-skip>
                <MarkdownView text={live.text} compact terms={terms} />
              </div>
            ) : (
              <p className="ask-tool">
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                正在读这一屏的原文…
              </p>
            )}
            {live.error && <p className="ask-err">{live.error}</p>}
          </article>
        )}
      </div>

      <form
        className="ask-input"
        onSubmit={(e) => {
          e.preventDefault()
          void send()
        }}
      >
        {quote && (
          <div className="ask-chip">
            <span className="min-w-0 flex-1 truncate" title={quote}>
              引用：{quote}
            </span>
            <button type="button" onClick={() => setQuote('')} aria-label="去掉引文">
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
        {notes.length > 0 && (
          <div className="ask-pending">
            <p className="ask-pending-head">
              <Highlighter className="h-3 w-3" aria-hidden />
              待发送的标注 {notes.length} 处，写一个问题一起发过去
            </p>
            <ul>
              {notes.map((n, i) => (
                <li key={n.id}>
                  <span className="i">{i + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="q" title={n.quote}>
                      {n.quote}
                    </span>
                    {n.note && <span className="n">我的备注：{n.note}</span>}
                  </span>
                  <button type="button" onClick={() => ask.dropNote(n.id)} aria-label="去掉这一处标注">
                    <X className="h-3 w-3" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <textarea
          ref={input}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              void send()
            }
          }}
          rows={3}
          placeholder={
            ready === false
              ? '先在上面配好模型，就能开始问了'
              : notes.length
                ? `这 ${notes.length} 处标注想问什么？（Ctrl+Enter 发送）`
                : quote
                  ? '这句话想问什么？'
                  : '问这一屏里任何看不懂的地方（Ctrl+Enter 发送）'
          }
          aria-label="你的问题"
        />
        <div className="ask-actions">
          <label title="让 AI 自己去读 notebook、报告、数据表的前几行；关掉就只看当前这一屏">
            <input type="checkbox" checked={useTools} onChange={(e) => setUseTools(e.target.checked)} />
            允许查项目文件
          </label>
          <button type="submit" disabled={!question.trim() || Boolean(live) || ready === false}>
            {live ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Send className="h-3.5 w-3.5" aria-hidden />}
            发送
          </button>
        </div>
      </form>
    </aside>
  )
}

/** 一条问答带的几处标注：原文 + 用户自己写的备注，按发出去时的序号列。 */
function NoteList({ notes }: { notes: { quote: string; note: string }[] }) {
  if (!notes.length) return null
  return (
    <ol className="ask-notes">
      {notes.map((n, i) => (
        <li key={i}>
          <span className="i">{i + 1}</span>
          <span className="min-w-0 flex-1">
            <span className="q">{n.quote}</span>
            {n.note && <span className="n">我的备注：{n.note}</span>}
          </span>
        </li>
      ))}
    </ol>
  )
}

/** 答案里提到的数据文件与单元格：点一下跳到数据选项卡的那张表、讲解里的那一格。 */
function Links({ pid, links }: { pid: string; links: AskLink[] }) {
  if (!links.length) return null
  const to = (l: AskLink) => {
    const path = encodeURIComponent(l.path ?? '')
    if (l.kind === 'cell') return `/p/${pid}/steps/${l.step}?tab=guide&cell=${l.cell}`
    if (l.kind === 'data') return l.step ? `/p/${pid}/steps/${l.step}?tab=data&open=${path}` : `/p/${pid}/data?tab=files&path=${path}`
    return l.step ? `/p/${pid}/steps/${l.step}?file=${path}` : `/p/${pid}/data?tab=files&path=${path}`
  }
  const icon = (l: AskLink) =>
    l.kind === 'cell' ? <BookOpen className="h-3 w-3" aria-hidden /> : l.kind === 'data' ? <Table2 className="h-3 w-3" aria-hidden /> : <FileCode2 className="h-3 w-3" aria-hidden />
  return (
    <p className="ask-links">
      <span>答案里提到的：</span>
      {links.map((l, i) => (
        <Link key={i} to={to(l)} title={l.kind === 'cell' ? '跳到讲解里的这一格' : l.path ?? ''}>
          {icon(l)}
          {l.label}
        </Link>
      ))}
    </p>
  )
}

function RecordCard({ pid, r, terms, focused, onChanged }: {
  pid: string
  r: AskRecord
  terms: ReturnType<typeof useTerms>
  focused: boolean
  onChanged: () => void
}) {
  const client = useQueryClient()
  const [saving, setSaving] = useState(false)
  const [term, setTerm] = useState('')
  const [meaning, setMeaning] = useState('')
  const mark = useMutation({ mutationFn: () => api.markAsk(pid, r.id, !r.mark, r.step), onSuccess: onChanged })
  const drop = useMutation({ mutationFn: () => api.deleteAsk(pid, r.id, r.step), onSuccess: onChanged })
  const save = useMutation({
    mutationFn: () => api.saveTerm(pid, r.id, { term: term.trim(), meaning: meaning.trim(), step: r.step, source: '平台答疑' }),
    onSuccess: () => {
      setSaving(false)
      onChanged()
      // 术语表当场重取：这个词在页面上立刻带虚线下划线，悬停就能看解释，不用刷新。
      // 讲解那一屏用的是 guide 里自带的那份词表，所以两处都要重取。
      client.invalidateQueries({ queryKey: ['terms'], refetchType: 'all' })
      client.invalidateQueries({ queryKey: ['guide'], refetchType: 'all' })
    },
  })
  const openForm = () => {
    setTerm(r.quote.length <= 20 ? r.quote : '')
    setMeaning(firstSentence(r.answer))
    setSaving(true)
  }
  return (
    <article id={`ask-${r.id}`} className={`ask-card${focused ? ' is-focus' : ''}`}>
      {r.quote && <blockquote className="ask-quote">{r.quote}</blockquote>}
      <NoteList notes={r.notes ?? []} />
      <p className="ask-q">{r.question}</p>
      {r.answer && (
        <div className="ask-a" data-ask-skip>
          <MarkdownView text={r.answer} compact terms={terms} />
        </div>
      )}
      {r.error && <p className="ask-err">{r.error}</p>}
      {r.unverified.length > 0 && (
        <p className="ask-warn">这些数字在这一屏的原文里没找到出处，别直接引用：{r.unverified.join('、')}</p>
      )}
      <Links pid={pid} links={r.links ?? []} />
      <footer className="ask-meta">
        <span>{fmt(r.at)}</span>
        {r.tools.length > 0 && <span title={r.tools.join('、')}>查了 {r.tools.length} 次项目文件</span>}
        {r.saved_term && <span className="text-emerald-700">已收进术语表：{r.saved_term}</span>}
        <button type="button" onClick={() => mark.mutate()} title={r.mark ? '取消页面上的高亮' : '把问过的那几句钉在页面上'} className={r.mark ? 'is-on' : ''}>
          <Highlighter className="h-3 w-3" aria-hidden />
          {r.mark ? '已钉在页面上' : '钉在页面上'}
        </button>
        {!r.saved_term && r.answer && (
          <button type="button" onClick={openForm} title="把这个行话收进项目术语表，以后各页面都能悬停看解释">
            <BookmarkPlus className="h-3 w-3" aria-hidden />
            收进术语表
          </button>
        )}
        <button type="button" onClick={() => drop.mutate()} aria-label="删掉这条问答">
          <Trash2 className="h-3 w-3" aria-hidden />
        </button>
      </footer>
      {saving && (
        <form
          className="ask-term"
          onSubmit={(e) => {
            e.preventDefault()
            if (term.trim() && meaning.trim()) save.mutate()
          }}
        >
          <input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="术语（照原文写）" aria-label="术语" />
          <input value={meaning} onChange={(e) => setMeaning(e.target.value)} placeholder="一句白话解释" aria-label="白话解释" />
          <div>
            <button type="submit" disabled={!term.trim() || !meaning.trim()}>
              登记
            </button>
            <button type="button" onClick={() => setSaving(false)}>
              取消
            </button>
          </div>
          {save.error && <p className="ask-err">{(save.error as Error).message}</p>}
        </form>
      )}
    </article>
  )
}
