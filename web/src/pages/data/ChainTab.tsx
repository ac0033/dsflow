import { Fragment, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Plus } from 'lucide-react'
import { api } from '../../api'
import { fmtInt } from '../../lib/format'
import type { ChainItem, DataOverview } from '../../types'
import RegisterForm from './RegisterForm'

/** 数据演变链：已登记数据集按阶段排成一行，看清每个阶段的数据是什么、多大、从哪来、由哪一步产出。 */
export default function ChainTab({ pid, overview, onOpen }: { pid: string; overview: DataOverview; onOpen: (path: string) => void }) {
  const [adding, setAdding] = useState(false)
  const registeredNames = new Set(overview.datasets.map((d) => d.name))
  const pending = overview.declared.filter((d) => !registeredNames.has(d.name))
  const stages = overview.stages.filter((s) => overview.chain.some((c) => c.stage === s.id))

  return (
    <div className="space-y-4">
      {pending.length > 0 && <Declared pid={pid} items={pending} />}
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold">已登记的数据集</h2>
        <span className="text-[11px] text-slate-500">登记只记路径与内容哈希，不复制数据；同名数据集内容变了会成为新版本</span>
        <button onClick={() => setAdding(!adding)} className="ml-auto inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-50">
          <Plus className="h-3 w-3" aria-hidden />
          登记数据集
        </button>
      </div>
      {adding && (
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <RegisterForm pid={pid} overview={overview} onDone={() => setAdding(false)} />
        </div>
      )}
      {!overview.chain.length ? (
        <p className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500">还没有登记数据集。在"数据文件"里选中文件点"登记为数据集"，或在上方登记。</p>
      ) : (
        <div className="flex items-start gap-2 overflow-x-auto pb-2">
          {stages.map((s, i) => (
            <Fragment key={s.id}>
              {i > 0 && <ArrowRight className="mt-9 h-4 w-4 shrink-0 text-slate-400" aria-hidden />}
              <section className="w-64 shrink-0" aria-label={s.label}>
                <h3 className="mb-1.5 text-xs font-semibold text-slate-600">{s.label}</h3>
                <div className="space-y-2">
                  {overview.chain
                    .filter((c) => c.stage === s.id)
                    .map((c) => (
                      <Card key={c.name} item={c} onOpen={onOpen} />
                    ))}
                </div>
              </section>
            </Fragment>
          ))}
        </div>
      )}
    </div>
  )
}

function Card({ item, onOpen }: { item: ChainItem; onOpen: (path: string) => void }) {
  return (
    <button onClick={() => onOpen(item.path)} className="block w-full rounded-lg border border-slate-200 bg-white p-2.5 text-left shadow-sm hover:border-blue-300">
      <div className="flex items-center gap-1.5">
        <span className="truncate text-sm font-medium">{item.name}</span>
        <span className="shrink-0 rounded bg-slate-100 px-1 font-mono text-[10px] text-slate-500">{item.version}</span>
      </div>
      <p className="tabular mt-0.5 text-xs text-slate-700">{item.rows != null ? `${fmtInt(item.rows)} 行 × ${item.columns} 列` : '尚未转换，行列数未知'}</p>
      <p className={`mt-0.5 text-[11px] ${item.description ? 'text-slate-500' : 'text-slate-400'}`}>
        {item.description || '还没有写这份数据的介绍。'}
      </p>
      <div className="mt-1.5 flex flex-wrap gap-1 text-[10px]">
        {item.parents.map((p) => (
          <span key={p} className="rounded bg-slate-100 px-1 text-slate-600">
            来自 {p}
          </span>
        ))}
        {item.produced_by && <span className="rounded bg-amber-50 px-1 text-amber-800">步骤 {item.produced_by} 产出</span>}
        {(item.used_by ?? []).map((u) => (
          <span key={u.step} className="rounded bg-violet-50 px-1 text-violet-800">
            {u.step} {u.role}
          </span>
        ))}
        {item.version_count > 1 && <span className="rounded bg-slate-100 px-1 text-slate-600">共 {item.version_count} 版</span>}
      </div>
      <p className="mt-1 truncate text-[10px] text-slate-400" title={item.path}>
        {item.path}
      </p>
    </button>
  )
}

function Declared({ pid, items }: { pid: string; items: DataOverview['declared'] }) {
  const qc = useQueryClient()
  const register = useMutation({
    mutationFn: async () => {
      for (const d of items) await api.register(pid, { path: d.path, name: d.name, stage: d.stage, parents: [], produced_by: null, description: d.description })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['data', pid] }),
  })
  return (
    <section className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
      <p>
        dsflow.yaml 声明了 {items.length} 个数据集还没登记：{items.map((d) => `${d.name}（${d.path}）`).join('、')}
      </p>
      <button onClick={() => register.mutate()} disabled={register.isPending} className="mt-2 rounded bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50">
        {register.isPending ? '登记中…' : '全部登记'}
      </button>
      {register.error && <p className="mt-1 text-xs text-red-700">{(register.error as Error).message}</p>}
    </section>
  )
}
