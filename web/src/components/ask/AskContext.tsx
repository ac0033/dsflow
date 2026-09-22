import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router'

/*
 * 答疑的共享状态：用户此刻在看哪一步、哪个选项卡、哪个文件，对话框开没开，手上带着哪一句引文。
 * 页面只做一件事——用 useAskScope 报告自己在哪；其余都由对话框（AskDock）读这里的状态。
 */

export interface AskScope {
  step?: string | null
  rev?: string | null
  tab?: string | null
  file?: string | null
}

export interface AskDraft {
  /** 用户选中的原文 */
  quote: string
}

/** 一处还没发出去的标注：选中的原文、用户自己写的备注、标的时候停在哪一页。 */
export interface AskNote {
  id: string
  quote: string
  note: string
  step: string | null
  tab: string | null
}

interface AskApi {
  pid: string
  scope: AskScope
  setScope: (scope: AskScope) => void
  open: boolean
  draft: AskDraft | null
  focus: string | null
  /** 还没发出去的标注，攒够了连同一个问题一起发 */
  notes: AskNote[]
  /** 打开对话框；带引文就把引文放进输入框上方 */
  ask: (draft?: Partial<AskDraft>) => void
  close: () => void
  clearDraft: () => void
  setFocus: (id: string | null) => void
  addNote: (quote: string, note: string) => void
  dropNote: (id: string) => void
  clearNotes: () => void
}

const AskCtx = createContext<AskApi | null>(null)

/** 不在项目里（比如欢迎页）时返回 null，调用方自己判断。 */
export const useAsk = () => useContext(AskCtx)

/** 没有页面报告位置时，按网址猜一个选项卡：总览下面的几页各算一个。 */
function fromPath(path: string): AskScope {
  const tab = /\/(flow|data|runs|models|tracker)(\/|$)/.exec(path)?.[1]
  return { tab: tab ?? (/\/p\/[^/]+$/.test(path) ? 'board' : null) }
}

export function AskProvider({ pid, children }: { pid: string; children: ReactNode }) {
  const path = useLocation().pathname
  // 位置和网址绑在一起：换了页面而新页面没报告位置时，自动退回按网址猜的那个，不会还停在上一步
  const [held, setHeld] = useState<{ path: string; scope: AskScope }>({ path, scope: {} })
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<AskDraft | null>(null)
  const [focus, setFocus] = useState<string | null>(null)
  const [notes, setNotes] = useState<AskNote[]>([])
  const scope = held.path === path ? held.scope : fromPath(path)

  const setScope = useCallback((next: AskScope) => {
    setHeld((prev) =>
      prev.path === window.location.pathname && prev.scope.step === next.step && prev.scope.rev === next.rev &&
      prev.scope.tab === next.tab && prev.scope.file === next.file
        ? prev
        : { path: window.location.pathname, scope: next },
    )
  }, [])

  const value = useMemo<AskApi>(
    () => ({
      pid,
      scope,
      setScope,
      open,
      draft,
      focus,
      notes,
      ask: (next) => {
        setDraft({ quote: next?.quote ?? '' })
        setFocus(null)
        setOpen(true)
      },
      close: () => setOpen(false),
      clearDraft: () => setDraft(null),
      setFocus: (id) => {
        setFocus(id)
        if (id) setOpen(true)
      },
      // 标注先攒在这里，不发给模型；用户在对话框里写好问题、点发送，这一批才一起提交
      addNote: (quote, note) =>
        setNotes((list) =>
          list.some((n) => n.quote === quote)
            ? list
            : [...list, { id: `n${Date.now().toString(36)}${list.length}`, quote, note, step: scope.step ?? null, tab: scope.tab ?? null }],
        ),
      dropNote: (id) => setNotes((list) => list.filter((n) => n.id !== id)),
      clearNotes: () => setNotes([]),
    }),
    [pid, scope, setScope, open, draft, focus, notes],
  )
  return <AskCtx.Provider value={value}>{children}</AskCtx.Provider>
}

/** 页面报告自己在哪：步骤、轮次、选项卡、正在看的文件。对话框据此组装上下文。 */
export function useAskScope(scope: AskScope) {
  const ask = useAsk()
  const setScope = ask?.setScope
  const key = `${scope.step ?? ''}|${scope.rev ?? ''}|${scope.tab ?? ''}|${scope.file ?? ''}`
  useEffect(() => {
    setScope?.({ step: scope.step ?? null, rev: scope.rev ?? null, tab: scope.tab ?? null, file: scope.file ?? null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, setScope])
}
