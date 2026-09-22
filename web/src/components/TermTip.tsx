import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Pin, X } from 'lucide-react'

/*
 * 术语解释的浮层：鼠标停在带虚线下划线的行话上就浮出来，点一下把它钉住。
 *
 * 位置由脚本算，不再用 CSS 的 ::after：先贴着词的左下角，右边放不下就整体往左推，下边放不下就翻到词的上方，
 * 永远留在窗口里，读者不必横向拖动页面去看后半句。
 * 钉住以后浮层不随鼠标消失，里面的解释可以选中复制，点别处或按 Esc 收起。
 */

const GAP = 6   // 浮层和词之间留的距离
const EDGE = 8  // 浮层离窗口边缘至少留的距离

interface Tip {
  term: string
  plain: string
  host: HTMLElement
  pinned: boolean
}

/** 落在窗口里的位置：先放词的下方，下方放不下就翻到上方；左右都夹回窗口内。 */
function place(host: HTMLElement, box: HTMLElement): { left: number; top: number } {
  const r = host.getBoundingClientRect()
  const w = box.offsetWidth
  const h = box.offsetHeight
  const left = Math.max(EDGE, Math.min(r.left, window.innerWidth - EDGE - w))
  const below = r.bottom + GAP
  const top = below + h <= window.innerHeight - EDGE ? below : Math.max(EDGE, r.top - GAP - h)
  return { left, top }
}

export default function TermTip() {
  const [tip, setTip] = useState<Tip | null>(null)
  const [at, setAt] = useState<{ left: number; top: number }>({ left: -9999, top: -9999 })
  const box = useRef<HTMLDivElement>(null)
  const now = useRef<Tip | null>(null)
  now.current = tip

  const show = useCallback((host: HTMLElement, pinned: boolean) => {
    const term = host.dataset.term ?? ''
    const plain = host.dataset.plain ?? ''
    if (!term && !plain) return
    setTip({ term, plain, host, pinned })
  }, [])

  // 位置：浮层一渲染出来就量一次自己的宽高，再按窗口边界摆好
  useLayoutEffect(() => {
    if (!tip || !box.current) return
    setAt(place(tip.host, box.current))
  }, [tip])

  // 钉住的时候跟着页面滚动走；没钉住的滚一下就收起，免得停在半空
  useEffect(() => {
    if (!tip) return
    const follow = () => {
      if (!box.current) return
      if (!tip.pinned) return setTip(null)
      setAt(place(tip.host, box.current))
    }
    window.addEventListener('scroll', follow, true)
    window.addEventListener('resize', follow)
    return () => {
      window.removeEventListener('scroll', follow, true)
      window.removeEventListener('resize', follow)
    }
  }, [tip])

  useEffect(() => {
    const term = (e: Event) => (e.target as HTMLElement | null)?.closest?.('.term') as HTMLElement | null
    const inBox = (e: Event) => Boolean((e.target as HTMLElement | null)?.closest?.('.term-tip'))

    const over = (e: PointerEvent) => {
      const host = term(e)
      setTip((now) => {
        if (now?.pinned) return now                       // 钉住的时候鼠标划过别的词不抢位置
        if (host) {
          if (now?.host === host) return now
          const [t, p] = [host.dataset.term ?? '', host.dataset.plain ?? '']
          return t || p ? { term: t, plain: p, host, pinned: false } : null
        }
        return inBox(e) ? now : null
      })
    }
    const click = (e: MouseEvent) => {
      const host = term(e)
      // 点已经钉住的那个词就收起，点另一个词就改钉它，点别处（浮层里除外）收起
      if (host) return now.current?.pinned && now.current.host === host ? setTip(null) : show(host, true)
      if (!inBox(e)) setTip(null)
    }
    const key = (e: KeyboardEvent) => {
      const host = (e.target as HTMLElement | null)?.closest?.('.term') as HTMLElement | null
      if (e.key === 'Escape') setTip(null)
      else if (e.key === 'Enter' && host) show(host, true)
    }
    const focus = (e: FocusEvent) => {
      const host = (e.target as HTMLElement | null)?.closest?.('.term') as HTMLElement | null
      if (host) show(host, false)
      else if (!now.current?.pinned && !(e.target as HTMLElement | null)?.closest?.('.term-tip')) setTip(null)
    }
    document.addEventListener('pointerover', over)
    document.addEventListener('click', click)
    document.addEventListener('keydown', key)
    document.addEventListener('focusin', focus)
    return () => {
      document.removeEventListener('pointerover', over)
      document.removeEventListener('click', click)
      document.removeEventListener('keydown', key)
      document.removeEventListener('focusin', focus)
    }
  }, [show])

  // 钉住的那个词自己也标一下，读者知道浮层说的是哪个词
  useEffect(() => {
    const host = tip?.pinned ? tip.host : null
    host?.classList.add('is-pinned')
    return () => host?.classList.remove('is-pinned')
  }, [tip])

  if (!tip) return null
  return createPortal(
    <div ref={box} className={`term-tip${tip.pinned ? ' is-pinned' : ''}`} style={{ left: at.left, top: at.top }} role="tooltip">
      <p className="term-tip-head">
        <span className="term-tip-name">{tip.term}</span>
        {tip.pinned ? (
          <button type="button" onClick={() => setTip(null)} aria-label="收起这条解释">
            <X className="h-3 w-3" aria-hidden />
          </button>
        ) : (
          <span className="term-tip-hint">
            <Pin className="h-3 w-3" aria-hidden />
            点一下钉住
          </span>
        )}
      </p>
      <p className="term-tip-plain">{tip.plain}</p>
    </div>,
    document.body,
  )
}
