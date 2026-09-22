import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api'
import ColumnPicker from '../../components/ColumnPicker'
import type { DataOverview } from '../../types'

/** 登记数据集：只记录路径与内容哈希，不复制数据；同名、内容变了就是新版本。 */
export default function RegisterForm({ pid, overview, initialPath, initialName, initialStage, initialDescription, onDone }: {
  pid: string
  overview: DataOverview
  initialPath?: string
  initialName?: string
  initialStage?: string
  initialDescription?: string
  onDone?: () => void
}) {
  const qc = useQueryClient()
  const [path, setPath] = useState(initialPath ?? '')
  const [name, setName] = useState(initialName ?? (initialPath?.split('/').pop()?.replace(/\.[^.]+$/, '') ?? ''))
  const [stage, setStage] = useState(initialStage ?? 'raw')
  const [parents, setParents] = useState<string[]>([])
  const [producedBy, setProducedBy] = useState('')
  const [description, setDescription] = useState(initialDescription ?? '')
  const save = useMutation({
    mutationFn: () => api.register(pid, { path, name: name.trim(), stage, parents, produced_by: producedBy.trim() || null, description }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['data', pid] })
      onDone?.()
    },
  })
  const field = 'rounded border border-slate-300 px-2 py-1 text-xs'
  return (
    <form
      className="grid gap-2 text-xs sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (path && name.trim() && description.trim()) save.mutate()
      }}
    >
      <label className="flex flex-col gap-0.5 sm:col-span-2">
        <span className="text-slate-500">文件</span>
        <select value={path} onChange={(e) => setPath(e.target.value)} className={field} required>
          <option value="">选择项目中的数据文件</option>
          {overview.files.map((f) => (
            <option key={f.path} value={f.path}>
              {f.path}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-0.5">
        <span className="text-slate-500">数据集名（逻辑名，跨版本不变）</span>
        <input value={name} onChange={(e) => setName(e.target.value)} className={field} placeholder="如 orders_raw" required />
      </label>
      <label className="flex flex-col gap-0.5">
        <span className="text-slate-500">阶段</span>
        <select value={stage} onChange={(e) => setStage(e.target.value)} className={field}>
          {overview.stages.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}（{s.id}）
            </option>
          ))}
        </select>
      </label>
      <div className="flex flex-col gap-0.5">
        <span className="text-slate-500">上游数据集（由哪些数据处理而来）</span>
        <ColumnPicker label="上游数据集" options={overview.datasets.map((d) => d.name)} value={parents} onChange={setParents} placeholder="无" />
      </div>
      <label className="flex flex-col gap-0.5">
        <span className="text-slate-500">产出步骤编号</span>
        <input value={producedBy} onChange={(e) => setProducedBy(e.target.value)} className={field} placeholder="如 1.2（原始数据留空）" />
      </label>
      <label className="flex flex-col gap-0.5 sm:col-span-2">
        <span className="text-slate-500">简要介绍（装的是什么、怎么来的、后面哪一步会用）</span>
        <input value={description} onChange={(e) => setDescription(e.target.value)} className={field} required placeholder="如：一行 = 一个订单号下的一个 SKU，按采购单导出，2.1 做质量分析用" />
      </label>
      <div className="flex items-center gap-2 sm:col-span-2">
        <button type="submit" disabled={save.isPending} className="rounded bg-blue-600 px-3 py-1.5 font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          {save.isPending ? '登记中（计算哈希）…' : '登记'}
        </button>
        {onDone && (
          <button type="button" onClick={onDone} className="text-slate-500 hover:text-slate-800">
            取消
          </button>
        )}
        {save.error && <span className="text-red-600">{(save.error as Error).message}</span>}
      </div>
    </form>
  )
}
