import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Highlighter, MessageCircleQuestion } from 'lucide-react'
import { useAsk } from './AskContext'

/*
 * 选中文字以后浮出来的两个按钮，各做一件事：
 * 「问 AI」把这句话当引文带进对话框，马上问；
 * 「标注」在原地写一句自己的备注，确认后先攒着不发——可以接着标别处，几处标完在对话框里写一个问题一起发过去。
 * 只在标了 data-ask-root 的内容区里生效，选中侧边栏、按钮文字不会弹。
 */

const MIN = 2
const MAX = 800

interface Spot {
  x: number
  y: number
  text: string
}

export default function SelectionAsk() {
  const ask = useAsk()
  const [spot, setSpot] = useState<Spot | null>(null)
  const [note, setNote] = useState<string | null>(null)   // 不是 null 就表示正在写备注
  const input = useRef<HTMLTextAreaElement>(null)
  const writing = note !== null

  useEffect(() => {
    const read = () => {
      if (writing) return                                  // 正在写备注时不跟着选区跑
      const selection = window.getSelection()
      if (!selection || selection.isCollapsed || !selection.rangeCount) return setSpot(null)
      const text = selection.toString().trim()
      if (text.length < MIN) return setSpot(null)
      const node = selection.anchorNode
      const host = node?.nodeType === Node.ELEMENT_NODE ? (node as HTMLElement) : (node?.parentElement ?? null)
      if (!host?.closest('[data-ask-root]')) return setSpot(null)
      const rect = selection.getRangeAt(0).getBoundingClientRect()
      if (!rect.width && !rect.height) return setSpot(null)
      setSpot({ x: rect.left + rect.width / 2, y: rect.top, text: text.slice(0, MAX) })
    }
    const clear = (e: MouseEvent) => {
      if ((e.target as HTMLElement | null)?.closest?.('.ask-pop')) return
      setSpot(null)
      setNote(null)
    }
    document.addEventListener('mouseup', read)
    document.addEventListener('keyup', read)
    document.addEventListener('mousedown', clear)
    return () => {
      document.removeEventListener('mouseup', read)
      document.removeEventListener('keyup', read)
      document.removeEventListener('mousedown', clear)
    }
  }, [writing])

  if (!ask || !spot) return null
  const done = () => {
    setSpot(null)
    setNote(null)
    window.getSelection()?.removeAllRanges()
  }
  const toAsk = () => {
    ask.ask({ quote: spot.text })
    done()
  }
  const keep = () => {
    ask.addNote(spot.text, (note ?? '').trim())
    done()
  }
  // 浮层自己夹在窗口里：选中的地方靠边时也不会把按钮或备注框推到屏幕外
  const half = writing ? 158 : 70
  const left = Math.min(Math.max(spot.x, half + 8), window.innerWidth - half - 8)
  const top = Math.max(spot.y, writing ? 160 : 46)
  return createPortal(
    <div className={`ask-pop${writing ? ' is-note' : ''}`} style={{ left, top }}>
      {writing ? (
        <form
          className="ask-note-form"
          onSubmit={(e) => {
            e.preventDefault()
            keep()
          }}
        >
          <p className="ask-note-quote" title={spot.text}>
            {spot.text}
          </p>
          <textarea
            ref={input}
            rows={2}
            value={note ?? ''}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                keep()
              } else if (e.key === 'Escape') setNote(null)
            }}
            placeholder="写一句你对这里的疑问或备注（可以留空，Enter 确认）"
            aria-label="这一处的备注"
          />
          <div className="ask-note-row">
            <span>确认后先留在页面上，几处标完一起发问。</span>
            <button type="button" onClick={() => setNote(null)}>
              取消
            </button>
            <button type="submit" className="go">
              确认标注
            </button>
          </div>
        </form>
      ) : (
        <>
          <button type="button" onClick={toAsk}>
            <MessageCircleQuestion className="h-3.5 w-3.5" aria-hidden />
            问 AI
          </button>
          <button
            type="button"
            onClick={() => {
              setNote('')
              window.setTimeout(() => input.current?.focus(), 30)
            }}
            title="写一句备注先标上，可以标多处，最后一起发问"
          >
            <Highlighter className="h-3.5 w-3.5" aria-hidden />
            标注
          </button>
        </>
      )}
    </div>,
    document.body,
  )
}
