import { useQuery } from '@tanstack/react-query'
import { api } from '../../api'
import { useScope } from '../../lib/scope'
import MainlineView from '../data/MainlineView'

/** 阶段的数据主线：本阶段每一步把哪张表变成了哪张表。和项目总览、步骤页用同一个视图与同一份来源。 */
export default function StageData() {
  const { pid, stage, stepIds } = useScope()
  const project = useQuery({ queryKey: ['project', pid], queryFn: () => api.project(pid) })
  const graph = project.data?.graph
  if (!stage || !stepIds) return null
  if (project.isLoading) return <p className="px-6 py-4 text-sm text-slate-500">读取…</p>
  if (!graph) return null
  const steps = graph.nodes.filter((n) => n.stage === stage.id).sort((a, b) => a.order - b.order)
  return (
    <div className="mx-auto max-w-5xl px-6 py-4">
      <MainlineView pid={pid} steps={steps} stages={graph.stages} />
    </div>
  )
}
