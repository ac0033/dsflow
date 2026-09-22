/*
 * 标注的高亮：把已经钉住的引文在页面上标出来。
 *
 * 用浏览器的 CSS 自定义高亮（CSS.highlights），不往 React 管的 DOM 里插标签——插标签会和 React 的重绘打架。
 * 浏览器不支持时就什么都不做，页面照常能看、能问，只是少了黄色底纹。
 */

type HighlightCtor = new (...ranges: Range[]) => object
type HighlightRegistry = { set(name: string, value: object): void; delete(name: string): void }

/** 两种高亮：已经问过并钉住的引文用黄色，还没发出去的标注用蓝色 */
export const ASKED = 'dsflow-ask'
export const NOTED = 'dsflow-note'

const registry = (): HighlightRegistry | null =>
  typeof CSS === 'undefined' ? null : ((CSS as unknown as { highlights?: HighlightRegistry }).highlights ?? null)
const ctor = (): HighlightCtor | null => (window as unknown as { Highlight?: HighlightCtor }).Highlight ?? null

export const canHighlight = () => Boolean(registry() && ctor())

interface Flat {
  text: string
  map: { node: Text; offset: number }[]
}

/** 把一棵子树里的文字连成一串，连续空白算一个空格；map 记住每个字符落在哪个文本节点的第几位。 */
function flatten(root: HTMLElement): Flat {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => {
      const parent = (node as Text).parentElement
      if (!node.nodeValue || !parent || parent.closest('[data-ask-skip]')) return NodeFilter.FILTER_REJECT
      return NodeFilter.FILTER_ACCEPT
    },
  })
  let text = ''
  const map: Flat['map'] = []
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const value = (node as Text).nodeValue ?? ''
    for (let i = 0; i < value.length; i++) {
      const blank = /\s/.test(value[i])
      if (blank && text.endsWith(' ')) continue
      text += blank ? ' ' : value[i]
      map.push({ node: node as Text, offset: i })
    }
  }
  return { text, map }
}

const normalize = (s: string) => s.replace(/\s+/g, ' ').trim()

/** 在页面里找出这句引文的位置；找不到（内容改过、不在这个选项卡）就返回 null。 */
export function rangeFor(root: HTMLElement, quote: string, flat?: Flat): Range | null {
  const needle = normalize(quote)
  if (!needle) return null
  const { text, map } = flat ?? flatten(root)
  const at = text.indexOf(needle)
  if (at < 0 || !map[at] || !map[at + needle.length - 1]) return null
  const start = map[at]
  const end = map[at + needle.length - 1]
  const range = document.createRange()
  try {
    range.setStart(start.node, start.offset)
    range.setEnd(end.node, end.offset + 1)
  } catch {
    return null
  }
  return range
}

export interface Marked {
  id: string
  range: Range
}

/** 把钉住的引文全部高亮；返回真的找到了位置的那些，供点击命中用。 */
export function applyMarks(root: HTMLElement | null, items: { id: string; quote: string }[], name: string = ASKED): Marked[] {
  const store = registry()
  const Ctor = ctor()
  if (!store || !Ctor) return []
  if (!root || !items.length) {
    store.delete(name)
    return []
  }
  const flat = flatten(root)
  const found: Marked[] = []
  for (const item of items) {
    const range = rangeFor(root, item.quote, flat)
    if (range) found.push({ id: item.id, range })
  }
  if (!found.length) store.delete(name)
  else store.set(name, new Ctor(...found.map((m) => m.range)))
  return found
}

export function clearMarks(name: string = ASKED): void {
  registry()?.delete(name)
}

/** 点在页面上的某个位置，落在哪条标注里。 */
export function hitTest(marks: Marked[], x: number, y: number): string | null {
  for (const mark of marks)
    for (const rect of Array.from(mark.range.getClientRects()))
      if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) return mark.id
  return null
}
