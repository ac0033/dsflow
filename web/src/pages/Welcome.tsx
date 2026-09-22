import { Link } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { Lock } from 'lucide-react'
import { api } from '../api'
import ImportProjectForm from '../components/ImportProjectForm'

/** 首页：全部项目 + 导入。进入项目后，左侧按生命周期阶段组织。 */
export default function Welcome() {
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })
  const list = projects.data ?? []
  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <h1 className="text-xl font-bold">选择项目</h1>
        <p className="mt-1 text-sm leading-relaxed text-slate-600">
          把数据科学项目的每一步变成可检查的状态变化：做了什么、数据怎样变化、凭什么说做对了、现在能说什么和不能说什么。项目文件是唯一事实来源，平台只读取、校验和展示。
        </p>
        {projects.isLoading && <p className="mt-4 text-sm text-slate-500">加载中…</p>}
        {projects.error && <p className="mt-4 text-sm text-red-600">{(projects.error as Error).message}</p>}
        {list.length > 0 && (
          <ul className="mt-5 grid gap-3 sm:grid-cols-2">
            {list.map((p) => {
              const done = p.status_counts.done ?? 0
              const waiting = (p.status_counts.pending_approval ?? 0) + (p.status_counts.awaiting_acceptance ?? 0)
              return (
                <li key={p.id}>
                  <Link to={`/p/${p.id}`} className="block rounded-lg border border-slate-200 bg-white p-4 hover:border-blue-300 hover:shadow-sm">
                    <span className="flex items-center gap-1.5 font-semibold">
                      {p.name}
                      {p.readonly && <Lock className="h-3.5 w-3.5 text-slate-400" aria-label="只读接入" />}
                    </span>
                    <span className="mt-0.5 block truncate font-mono text-[11px] text-slate-500" title={p.root}>
                      {p.root}
                    </span>
                    <span className="mt-2 block text-xs text-slate-600">
                      {p.step_count ?? 0} 个步骤 · 完成 {done}
                      {waiting ? ` · 待你处理 ${waiting}` : ''} · {p.readonly ? '只读接入' : '可写'}
                      {p.error_count ? <span className="text-red-600"> · {p.error_count} 个校验问题</span> : null}
                    </span>
                  </Link>
                </li>
              )
            })}
          </ul>
        )}
        <section className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold">导入项目目录</h2>
          <ImportProjectForm />
        </section>
        <section className="mt-4 text-sm text-slate-600">
          <h2 className="mb-1 text-sm font-semibold text-slate-800">也可以在命令行</h2>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              新建项目：<code className="rounded bg-slate-100 px-1">uv run dsflow init 目录 --name 项目名</code>
            </li>
            <li>
              校验项目：<code className="rounded bg-slate-100 px-1">uv run dsflow validate 目录</code>
            </li>
            <li>
              交接前核对：<code className="rounded bg-slate-100 px-1">uv run dsflow check 目录</code>
            </li>
          </ul>
        </section>
      </div>
    </div>
  )
}
