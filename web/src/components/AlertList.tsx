import { Link } from 'react-router'
import { AlertCircle, AlertTriangle, Info, XOctagon } from 'lucide-react'
import type { Alert, AlertLevel } from '../types'

/** 告警等级：图标 + 文字标签 + 颜色，三者一起表达，不单靠颜色。 */
export const LEVEL: Record<AlertLevel, { label: string; icon: typeof Info; box: string; text: string }> = {
  critical: { label: '严重', icon: XOctagon, box: 'border-red-300 bg-red-50', text: 'text-red-800' },
  serious: { label: '重要', icon: AlertTriangle, box: 'border-orange-300 bg-orange-50', text: 'text-orange-800' },
  warning: { label: '注意', icon: AlertCircle, box: 'border-amber-200 bg-amber-50', text: 'text-amber-900' },
  info: { label: '提示', icon: Info, box: 'border-slate-200 bg-slate-50', text: 'text-slate-700' },
}

export function alertHref(pid: string, a: Alert): string | null {
  if (a.link?.startsWith('runs/') || a.link?.startsWith('models/')) return `/p/${pid}/${a.link}`
  if (a.link) return `/p/${pid}/data?tab=files&path=${encodeURIComponent(a.link)}`
  if (a.step) return `/p/${pid}/steps/${a.step}`
  return null
}

export default function AlertList({ pid, alerts }: { pid: string; alerts: Alert[] }) {
  return (
    <ul className="space-y-1.5">
      {alerts.map((a, i) => {
        const s = LEVEL[a.level]
        const href = alertHref(pid, a)
        return (
          <li key={i} className={`flex items-start gap-2 rounded-md border px-2.5 py-1.5 text-sm ${s.box}`}>
            <span className={`inline-flex shrink-0 items-center gap-1 pt-px text-xs font-semibold ${s.text}`}>
              <s.icon className="h-3.5 w-3.5" aria-hidden />
              {s.label}
            </span>
            <span className="min-w-0 flex-1 leading-relaxed">{a.message}</span>
            {href && (
              <Link to={href} className="shrink-0 text-xs text-blue-700 underline underline-offset-2">
                {a.link?.startsWith('runs/') ? '看运行' : a.link?.startsWith('models/') ? '看模型' : a.link ? '看数据' : `看 ${a.step}`}
              </Link>
            )}
          </li>
        )
      })}
    </ul>
  )
}
