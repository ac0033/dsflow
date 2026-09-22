import { useParams, useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { Lock } from 'lucide-react'
import { api } from '../../api'
import ChainTab from './ChainTab'
import CompareTab from './CompareTab'
import FilesTab from './FilesTab'
import MainlineView from './MainlineView'

const TABS = [
  { id: 'mainline', label: '数据主线' },
  { id: 'files', label: '数据文件' },
  { id: 'compare', label: '版本对比' },
  { id: 'chain', label: '演变链与登记' },
] as const

/**
 * 全项目的数据。默认是数据主线：按阶段、按步骤，每一步把哪张表变成了哪张表（和阶段板块、步骤页同一个视图）。
 * 其余三个是工具：浏览任意数据文件（按需分页）、任意两版对比、数据集演变链与登记。
 */
export default function DataPage() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'mainline'
  const overview = useQuery({ queryKey: ['data', id], queryFn: () => api.data(id) })
  const project = useQuery({ queryKey: ['project', id], queryFn: () => api.project(id) })
  const graph = project.data?.graph

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    Object.entries(patch).forEach(([k, v]) => (v == null ? next.delete(k) : next.set(k, v)))
    setParams(next)
  }

  return (
    <div className="mx-auto max-w-[1440px] px-6 py-4">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-md border border-slate-200 bg-white p-0.5" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => update({ tab: t.id })}
              className={`rounded px-3 py-1 text-sm ${tab === t.id ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
            >
              {t.label}
            </button>
          ))}
        </div>
        {overview.data?.readonly && (
          <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600" title="转换缓存、画像、登记都存放在平台目录，不写入项目">
            <Lock className="h-3 w-3" aria-hidden />
            只读接入：缓存与登记放在平台目录
          </span>
        )}
      </div>
      {tab === 'mainline' &&
        (graph ? (
          <div className="mx-auto max-w-5xl">
            <MainlineView pid={id} steps={[...graph.nodes].sort((a, b) => a.order - b.order)} stages={graph.stages} groupByStage />
          </div>
        ) : (
          <p className="text-sm text-slate-500">{project.error ? (project.error as Error).message : '读取步骤…'}</p>
        ))}
      {tab !== 'mainline' && overview.isLoading && <p className="text-sm text-slate-500">正在扫描项目中的数据文件…</p>}
      {overview.error && <p className="text-sm text-red-600">{(overview.error as Error).message}</p>}
      {overview.data && tab === 'files' && (
        <FilesTab
          pid={id}
          overview={overview.data}
          files={overview.data.files.filter((f) => f.stage == null)}
          path={params.get('path')}
          onSelect={(path) => update({ path })}
          note="这里只列不属于某一个阶段的文件：原始数据，以及全项目共用的表。放在某个步骤目录下的、或登记时写明由某一步产出的文件，在那个阶段的「数据文件」里。"
        />
      )}
      {overview.data && tab === 'compare' && <CompareTab pid={id} overview={overview.data} />}
      {overview.data && tab === 'chain' && (
        <ChainTab pid={id} overview={overview.data} onOpen={(path) => update({ tab: 'files', path })} />
      )}
    </div>
  )
}
