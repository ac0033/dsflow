import { useCallback } from 'react'
import { useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api'
import { useScope } from '../../lib/scope'
import FilesTab, { byDir, type FileGroup } from '../data/FilesTab'
import type { DataFile } from '../../types'

/*
 * 阶段的数据文件：本阶段的每一个数据文件都在这里，含各步骤产出的中间文件。
 * 归属两条线（后端 `attribute` 定的）：文件放在这个阶段的目录下，或登记时写明由本阶段的某一步产出。
 * 分组按步骤，找文件时对着左边的步骤名就能索引；不挂在某一步上的按目录归一组。
 */
export default function StageFiles() {
  const { pid, stage } = useScope()
  const [params, setParams] = useSearchParams()
  const overview = useQuery({ queryKey: ['data', pid], queryFn: () => api.data(pid) })
  const project = useQuery({ queryKey: ['project', pid], queryFn: () => api.project(pid) })
  const titles = new Map((project.data?.graph?.nodes ?? []).map((n) => [n.id, n.title]))

  const groupOf = useCallback(
    (f: DataFile): FileGroup =>
      f.step ? { key: `1_${f.step}`, label: `${f.step} ${titles.get(f.step) ?? ''}`.trim(), note: dirOf(f) } : { key: `2_${byDir(f).key}`, label: byDir(f).label },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [project.data],
  )

  if (!stage) return null
  if (overview.isLoading) return <p className="px-6 py-4 text-sm text-slate-500">正在扫描项目中的数据文件…</p>
  if (overview.error) return <p className="px-6 py-4 text-sm text-red-600">{(overview.error as Error).message}</p>
  if (!overview.data) return null
  const files = overview.data.files.filter((f) => f.stage === stage.id)

  return (
    <div className="px-6 py-4">
      {files.length ? (
        <FilesTab
          pid={pid}
          overview={overview.data}
          files={files}
          path={params.get('path')}
          onSelect={(path) => {
            const next = new URLSearchParams(params)
            next.set('path', path)
            setParams(next)
          }}
          groupOf={groupOf}
          note={`${stage.name}的数据文件共 ${files.length} 个：放在本阶段目录下的，加上登记时写明由本阶段某一步产出的（含中间文件）。`}
        />
      ) : (
        <p className="rounded-lg border border-dashed border-slate-300 p-6 text-sm leading-relaxed text-slate-600">
          这个阶段名下还没有数据文件。文件放进本阶段的步骤目录，或者登记数据集时写明由本阶段的某一步产出，它就会出现在这里；
          不属于任何阶段的文件在总览的「数据 › 数据文件」里。
        </p>
      )}
    </div>
  )
}

const dirOf = (f: DataFile) => (f.path.includes('/') ? f.path.slice(0, f.path.lastIndexOf('/')) : '')
