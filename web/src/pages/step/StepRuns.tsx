import { useQuery } from '@tanstack/react-query'
import { api } from '../../api'
import RunDetail from '../runs/RunDetail'
import RunsTable from '../runs/RunsTable'

/** 步骤页"运行与尝试"：本步的全部运行（含失败、无效、无结论），点一行在下方看详情。 */
export default function StepRuns({ pid, stepId, runId, onOpen }: { pid: string; stepId: string; runId: string | null; onOpen: (id: string | null) => void }) {
  const runs = useQuery({ queryKey: ['runs', pid, stepId], queryFn: () => api.runs(pid, stepId), refetchInterval: 5000 })
  if (runs.isLoading) return <p className="text-sm text-slate-500">读取运行记录…</p>
  const list = runs.data ?? []
  if (!list.length)
    return (
      <p className="max-w-3xl rounded-lg border border-dashed border-slate-300 p-6 text-sm leading-relaxed text-slate-600">
        本步还没有运行记录。在本步的脚本里用 <code className="rounded bg-slate-100 px-1">dsflow.start_run("{stepId}", hypothesis="…")</code> 记录，或者用{' '}
        <code className="rounded bg-slate-100 px-1">uv run dsflow run {stepId} -p 项目目录 -- 命令</code> 运行。
      </p>
    )
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-700">
        本步共 {list.length} 次运行，最近一次{list[0].status === 'succeeded' ? '成功' : list[0].status === 'failed' ? '失败' : '还在运行'}
        {list[0].conclusion ? `：${list[0].conclusion}` : ''}。
      </p>
      <RunsTable runs={list} onOpen={(id) => onOpen(id === runId ? null : id)} active={runId} />
      {runId && <RunDetail pid={pid} runId={runId} />}
    </div>
  )
}
