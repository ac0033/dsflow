import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'

interface Props {
  options: string[]
  value: string[]
  onChange: (value: string[]) => void
  placeholder?: string
  multiple?: boolean
  label: string
}

/** 可搜索的列选择器（单选或多选）。宽表几十上百列时靠搜索定位。 */
export default function ColumnPicker({ options, value, onChange, placeholder = '选择列', multiple = true, label }: Props) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])
  const shown = options.filter((o) => o.toLowerCase().includes(q.toLowerCase())).slice(0, 300)
  const toggle = (o: string) => {
    if (!multiple) {
      onChange(value[0] === o ? [] : [o])
      setOpen(false)
      return
    }
    onChange(value.includes(o) ? value.filter((v) => v !== o) : [...value, o])
  }
  return (
    <div ref={ref} className="relative inline-block min-w-40">
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-left text-xs hover:border-slate-400"
      >
        <span className={`truncate ${value.length ? '' : 'text-slate-400'}`}>{value.length ? value.join('、') : placeholder}</span>
        <ChevronDown className="h-3 w-3 shrink-0 text-slate-400" aria-hidden />
      </button>
      {open && (
        <div className="absolute z-40 mt-1 w-64 rounded-md border border-slate-200 bg-white p-1.5 shadow-lg">
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索列名"
            className="mb-1 w-full rounded border border-slate-200 px-2 py-1 text-xs outline-none focus:border-blue-500"
          />
          <ul className="max-h-60 overflow-auto text-xs" role="listbox" aria-multiselectable={multiple}>
            {shown.map((o) => (
              <li key={o}>
                <label className="flex cursor-pointer items-center gap-1.5 rounded px-1.5 py-1 hover:bg-slate-100">
                  <input type={multiple ? 'checkbox' : 'radio'} checked={value.includes(o)} onChange={() => toggle(o)} />
                  <span className="truncate">{o}</span>
                </label>
              </li>
            ))}
            {!shown.length && <li className="px-1.5 py-1 text-slate-400">没有匹配的列</li>}
          </ul>
          {value.length > 0 && (
            <button type="button" onClick={() => onChange([])} className="mt-1 text-[11px] text-slate-500 hover:text-slate-800">
              清空
            </button>
          )}
        </div>
      )}
    </div>
  )
}
