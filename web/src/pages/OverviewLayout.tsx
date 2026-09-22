import { Suspense, useMemo } from 'react'
import { Link, Outlet, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Lock } from 'lucide-react'
import { api } from '../api'
import LifecycleStrip from '../components/LifecycleStrip'
import TabGroups, { type TabGroup } from '../components/TabGroups'
import { ScopeContext, type Scope } from '../lib/scope'

/** 总览板块：生命周期条 + 分组选项卡。看板、流程图、问题与决策都是跨阶段的，放在这里；知识边界并进了各步看板（分析结论 / 易错点）和运行页（停止规则）。 */
export default function OverviewLayout() {
  const { id = '' } = useParams()
  const project = useQuery({ queryKey: ['project', id], queryFn: () => api.project(id) })
  const p = project.data?.project
  const graph = project.data?.graph
  const errors = project.data?.issues.filter((i) => i.severity === 'error') ?? []
  const base = `/p/${id}`
  const scope = useMemo<Scope>(() => ({ pid: id, stage: null, stepIds: null, base }), [id, base])
  // 和阶段、步骤同一套三层：业务层｜数据层｜执行层
  const groups: TabGroup[] = [
    {
      label: '业务层',
      items: [
        { key: 'board', label: '看板', to: base, end: true },
        { key: 'flow', label: '流程图', to: `${base}/flow` },
        { key: 'tracker', label: '问题与决策', to: `${base}/tracker` },
      ],
    },
    { label: '数据层', items: [{ key: 'data', label: '数据', to: `${base}/data` }] },
    {
      label: '执行层',
      items: [
        { key: 'runs', label: '运行与实验', to: `${base}/runs` },
        { key: 'models', label: '模型与交付', to: `${base}/models` },
      ],
    },
  ]

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-slate-100 bg-white px-6 pt-3">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-bold">项目总览</h1>
          {p?.readonly && (
            <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600" title="平台只读取项目文件，状态写在平台目录">
              <Lock className="h-3 w-3" aria-hidden />
              只读接入
            </span>
          )}
          {project.data &&
            (errors.length ? (
              <Link to={`${base}/flow`} className="inline-flex items-center gap-1 rounded bg-red-50 px-1.5 py-0.5 text-[11px] text-red-700 hover:underline">
                <AlertTriangle className="h-3 w-3" aria-hidden />
                {errors.length} 个校验问题
              </Link>
            ) : (
              <span className="inline-flex items-center gap-1 rounded bg-green-50 px-1.5 py-0.5 text-[11px] text-green-700">
                <CheckCircle2 className="h-3 w-3" aria-hidden />
                校验通过
              </span>
            ))}
        </div>
        {p?.question && <p className="mt-0.5 text-sm text-slate-600">业务问题：{p.question}</p>}
        {project.error && <p className="mt-1 text-sm text-red-600">{(project.error as Error).message}</p>}
        {graph && (
          <div className="mt-2">
            <LifecycleStrip pid={id} graph={graph} />
          </div>
        )}
        <TabGroups groups={groups} className="mt-1 border-b-0" />
      </div>
      <ScopeContext.Provider value={scope}>
        <div className="min-h-0 flex-1 overflow-auto">
          <Suspense fallback={<p className="p-6 text-sm text-slate-500">加载页面…</p>}>
            <Outlet />
          </Suspense>
        </div>
      </ScopeContext.Provider>
    </div>
  )
}
