import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { api } from '../../api'
import StopCard from '../../components/StopCard'
import { inScope, stageKind, useScope } from '../../lib/scope'
import type { Run } from '../../types'
import CompareRuns from './CompareRuns'
import RunDetail from './RunDetail'
import RunsTable from './RunsTable'

/** 运行与实验：全部运行记录（在阶段里只列本阶段步骤的），筛选、多选对比；建模类阶段先给停止规则曲线。 */
export default function RunsPage() {
  const { runId } = useParams()
  const scope = useScope()
  const { pid: id, stage, base } = scope
  const navigate = useNavigate()
  const runs = useQuery({ queryKey: ['runs', id], queryFn: () => api.runs(id), refetchInterval: 5000 })
  const isModel = !!stage && stageKind(stage.id) === 'model'
  const knowledge = useQuery({ queryKey: ['knowledge', id], queryFn: () => api.knowledge(id), enabled: isModel })
  const title = !stage ? '运行与实验' : isModel ? '实验对比' : '运行记录'
  const [step, setStep] = useState('')
  const [status, setStatus] = useState('')
  const [validity, setValidity] = useState('')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const all = useMemo(() => (runs.data ?? []).filter((r) => inScope(scope, r.step)), [runs.data, scope])
  const shown = useMemo(
    () =>
      all.filter(
        (r) =>
          (!step || r.step === step) &&
          (!status || r.status === status) &&
          (!validity || (validity === '未判断' ? !r.validity : r.validity === validity)) &&
          (!q || `${r.hypothesis} ${r.conclusion} ${r.run_id}`.includes(q)),
      ),
    [all, step, status, validity, q],
  )
  const picked = all.filter((r) => selected.has(r.run_id))
  const rules = (knowledge.data?.stop_rules ?? []).filter((r) => inScope(scope, r.step))
  const toggle = (rid: string) =>
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(rid)) n.delete(rid)
      else n.add(rid)
      return n
    })
  const counts = (pred: (r: Run) => boolean) => all.filter(pred).length

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-4">
      {runId ? (
        <>
          <nav className="mb-3 flex items-center gap-1 text-xs text-slate-500">
            <Link to={`${base}/runs`} className="hover:underline">
              {title}
            </Link>
            <ChevronRight className="h-3 w-3" aria-hidden />
            <span className="font-mono">{runId}</span>
          </nav>
          <RunDetail pid={id} runId={runId} />
        </>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-700">
            {stage ? '本阶段' : ''}共 {all.length} 次运行：成功 {counts((r) => r.status === 'succeeded')}、失败 {counts((r) => r.status === 'failed')}、运行中 {counts((r) => r.status === 'running')}；
            结论有效 {counts((r) => r.validity === '有效')}、无效 {counts((r) => r.validity === '无效')}、无结论 {counts((r) => r.validity === '无结论')}。无效和无结论的尝试同样保留。
          </p>
          {isModel && rules.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold">停止规则：同一指标每次尝试相对之前最好成绩的提升</h2>
              <div className="grid gap-4 lg:grid-cols-2">
                {rules.map((r) => (
                  <StopCard key={`${r.step}-${r.metric}`} pid={id} r={r} />
                ))}
              </div>
            </section>
          )}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <select value={step} onChange={(e) => setStep(e.target.value)} aria-label="步骤" className="rounded border border-slate-300 bg-white px-1.5 py-1">
              <option value="">全部步骤</option>
              {[...new Set(all.map((r) => r.step))].sort().map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="状态" className="rounded border border-slate-300 bg-white px-1.5 py-1">
              <option value="">全部状态</option>
              <option value="succeeded">成功</option>
              <option value="failed">失败</option>
              <option value="running">运行中</option>
            </select>
            <select value={validity} onChange={(e) => setValidity(e.target.value)} aria-label="有效性" className="rounded border border-slate-300 bg-white px-1.5 py-1">
              <option value="">全部有效性</option>
              {['有效', '无效', '无结论', '未判断'].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索假设、结论" aria-label="搜索" className="rounded border border-slate-300 px-2 py-1" />
            <span className="text-slate-500">勾选 2 次以上运行可以对比</span>
            {selected.size > 0 && (
              <button onClick={() => setSelected(new Set())} className="text-slate-500 underline">
                清空选择
              </button>
            )}
          </div>
          {runs.isLoading && <p className="text-sm text-slate-500">读取运行记录…</p>}
          {!runs.isLoading && !all.length && (
            <div className="rounded-lg border border-dashed border-slate-300 p-6 text-sm leading-relaxed text-slate-600">
              {stage ? '本阶段' : '项目'}还没有运行记录。两种记录方式：
              <ol className="mt-2 list-decimal space-y-1 pl-5">
                <li>
                  在脚本里用 SDK：<code className="rounded bg-slate-100 px-1">with dsflow.start_run("1.2", hypothesis="…") as run:</code> 记录输入、参数、指标、输出和结论；
                </li>
                <li>
                  用命令行包一层：<code className="rounded bg-slate-100 px-1">uv run dsflow run 1.2 -p 项目目录 -- python -m dsflow.tracking.notebook steps/…/nb_1.2.ipynb</code>，日志和退出码自动记录，notebook 里的 SDK 会写进同一条记录。
                </li>
              </ol>
            </div>
          )}
          {picked.length >= 2 && <CompareRuns key={[...selected].join()} runs={picked} />}
          <RunsTable runs={shown} showStep selected={selected} onToggle={toggle} onOpen={(rid) => navigate(`${base}/runs/${rid}`)} />
        </div>
      )}
    </div>
  )
}
