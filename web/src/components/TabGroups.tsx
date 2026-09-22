import { NavLink } from 'react-router'

export interface TabItem {
  key: string
  label: string
  count?: number | null
  /** 路由选项卡 */
  to?: string
  end?: boolean
  /** 页内选项卡 */
  active?: boolean
  onClick?: () => void
}

export interface TabGroup {
  label: string
  items: TabItem[]
}

const cls = (active: boolean) =>
  `-mb-px shrink-0 whitespace-nowrap border-b-2 px-2.5 py-1.5 text-sm ${active ? 'border-blue-600 font-medium text-blue-700' : 'border-transparent text-slate-600 hover:text-slate-900'}`

/** 分组选项卡：每组上方一行小字写类别，组之间用竖线隔开，组内按工作顺序排列。 */
export default function TabGroups({ groups, className = '' }: { groups: TabGroup[]; className?: string }) {
  const shown = groups.filter((g) => g.items.length)
  return (
    <nav className={`flex items-end overflow-x-auto border-b border-slate-200 ${className}`} aria-label="视图">
      {shown.map((g, gi) => (
        <div key={g.label} role="group" aria-label={g.label} className={`flex shrink-0 flex-col ${gi ? 'ml-1.5 border-l border-slate-200 pl-1.5' : ''}`}>
          <span className="px-2.5 text-[10px] tracking-wider text-slate-400">{g.label}</span>
          <div className="flex">
            {g.items.map((t) => {
              const count = t.count != null && <span className="ml-1 text-[11px] font-normal text-slate-400">{t.count}</span>
              return t.to != null ? (
                <NavLink key={t.key} to={t.to} end={t.end} className={({ isActive }) => cls(isActive)}>
                  {t.label}
                  {count}
                </NavLink>
              ) : (
                <button key={t.key} role="tab" aria-selected={!!t.active} onClick={t.onClick} className={cls(!!t.active)}>
                  {t.label}
                  {count}
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </nav>
  )
}
