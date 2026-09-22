import { Suspense, useMemo } from 'react'
import { Link, Outlet, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import { api } from '../../api'
import TabGroups, { type TabGroup, type TabItem } from '../../components/TabGroups'
import { ScopeContext, stageKind, type Scope } from '../../lib/scope'

/** 阶段板块：阶段头 + 按阶段性质定的分组选项卡；下面的页面都只显示本阶段步骤的内容。 */
export default function StageLayout() {
  const { id = '', stageId = '' } = useParams()
  const project = useQuery({ queryKey: ['project', id], queryFn: () => api.project(id) })
  const models = useQuery({ queryKey: ['models', id], queryFn: () => api.models(id) })
  const graph = project.data?.graph
  const stage = graph?.stages.find((s) => String(s.id) === stageId) ?? null
  const steps = useMemo(() => (graph && stage ? graph.nodes.filter((n) => n.stage === stage.id) : []), [graph, stage])
  const base = `/p/${id}/stage/${stageId}`
  const scope = useMemo<Scope>(() => ({ pid: id, stage, stepIds: new Set(steps.map((s) => s.id)), base }), [id, stage, steps, base])

  if (project.isLoading) return <p className="p-6 text-sm text-slate-500">加载中…</p>
  if (project.error) return <p className="p-6 text-sm text-red-600">{(project.error as Error).message}</p>
  if (!graph || !stage) return <p className="p-6 text-sm text-slate-600">这个项目里没有编号为 {stageId} 的阶段。</p>

  const kind = stageKind(stage.id)
  const hasModels = (models.data?.models ?? []).some((m) => m.versions.some((v) => v.step && scope.stepIds!.has(v.step)))
  const tab = {
    overview: { key: 'overview', label: '概况', to: base, end: true },
    data: { key: 'data', label: '数据主线', to: `${base}/data` },
    files: { key: 'files', label: '数据文件', to: `${base}/files` },
    runs: { key: 'runs', label: kind === 'model' ? '实验对比' : '运行记录', to: `${base}/runs` },
    models: { key: 'models', label: kind === 'delivery' ? '模型与交付' : '模型', to: `${base}/models` },
  } satisfies Record<string, TabItem>
  // 和步骤页同一套三层：业务层（概况 = 各步讲解的开头）｜数据层（数据主线）｜执行层（运行记录 / 实验对比、模型）。问题与决策只在总览有一份
  const process: TabItem[] = kind === 'data' ? [tab.runs] : kind === 'model' ? [tab.runs, ...(hasModels ? [tab.models] : [])] : [tab.models, tab.runs]
  const groups: TabGroup[] = [
    { label: '业务层', items: [tab.overview] },
    { label: '数据层', items: [tab.data, tab.files] },
    { label: '执行层', items: process },
  ]
  const index = graph.stages.findIndex((s) => s.id === stage.id)
  const prev = graph.stages[index - 1]
  const next = graph.stages[index + 1]
  const done = steps.filter((s) => s.status === 'done').length

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-slate-100 bg-white px-6 pt-3" style={{ borderTop: `3px solid ${stage.color}` }}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h1 className="text-lg font-bold" style={{ color: stage.color }}>
            {stage.name}
          </h1>
          <span className="text-xs text-slate-500">
            第 {index + 1} / {graph.stages.length} 个阶段 · {steps.length ? `${steps.length} 步，完成 ${done}` : '还没有登记步骤'}
          </span>
          <span className="ml-auto flex gap-1 text-xs">
            {prev && (
              <Link to={`/p/${id}/stage/${prev.id}`} className="inline-flex items-center gap-0.5 rounded border border-slate-300 px-2 py-0.5 text-slate-600 hover:bg-slate-50" title={`上一个阶段：${prev.name}`}>
                <ArrowLeft className="h-3 w-3" aria-hidden />
                {prev.name}
              </Link>
            )}
            {next && (
              <Link to={`/p/${id}/stage/${next.id}`} className="inline-flex items-center gap-0.5 rounded border border-slate-300 px-2 py-0.5 text-slate-600 hover:bg-slate-50" title={`下一个阶段：${next.name}`}>
                {next.name}
                <ArrowRight className="h-3 w-3" aria-hidden />
              </Link>
            )}
          </span>
        </div>
        <TabGroups groups={groups} className="mt-2 border-b-0" />
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
