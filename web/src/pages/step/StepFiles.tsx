import { useEffect, useState } from 'react'
import FileViewer from '../../components/FileViewer'
import type { TermIndex } from '../../components/Terms'
import { fmtBytes } from '../../lib/format'
import type { FileEntry } from '../../types'

export const KIND_LABEL: Record<string, string> = {
  plan: '计划', plan_user: '用户版计划', approval: '审批记录', planning: '计划材料', report: '用户报告',
  acceptance_report: '验收报告', acceptance_code: '验收代码', acceptance_material: '验收材料',
  execution_record: '执行记录', notebook: 'notebook', code: '代码', output: '产物', evidence: '报告证据',
  card: '说明卡', guide: '讲解', operation: '历史操作', doc: '文档', other: '其他',
}

/** 一组文档的切换阅读：只有一个就直接显示，多个用标签切换。 */
export function DocTabs({ pid, root, openFile, files, empty, labelOf, terms }: {
  pid: string
  root?: string
  openFile: (path: string) => void
  files: FileEntry[]
  empty: string
  labelOf?: (f: FileEntry) => string
  /** 术语提示：执行计划、代码说明里的行话也要能悬停看解释 */
  terms?: TermIndex
}) {
  const [sel, setSel] = useState(files[0]?.path)
  useEffect(() => setSel(files[0]?.path), [files])
  if (!files.length) return <p className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500">{empty}</p>
  const current = files.find((f) => f.path === sel) ?? files[0]
  return (
    <div className="space-y-2">
      {files.length > 1 && (
        <div className="flex flex-wrap gap-1.5 text-xs">
          {files.map((f) => (
            <button
              key={f.path}
              onClick={() => setSel(f.path)}
              className={`rounded-full border px-2 py-0.5 ${f.path === current.path ? 'border-blue-500 bg-blue-50 text-blue-800' : 'border-slate-300 bg-white hover:bg-slate-50'}`}
              title={f.path}
            >
              {labelOf ? labelOf(f) : `${KIND_LABEL[f.kind] ?? f.kind}：${f.rel}`}
            </button>
          ))}
        </div>
      )}
      <FileViewer pid={pid} path={current.path} projectRoot={root} onOpenFile={openFile} terms={terms} />
    </div>
  )
}

/** 本轮目录下的全部文件，按第一层文件夹分组，标出每个文件的角色。 */
export function FilesTree({ files, truncated, onOpen }: { files: FileEntry[]; truncated: boolean; onOpen: (path: string) => void }) {
  const groups = new Map<string, FileEntry[]>()
  files.forEach((f) => {
    const top = f.rel.includes('/') ? f.rel.split('/')[0] : '（本轮根目录）'
    groups.set(top, [...(groups.get(top) ?? []), f])
  })
  if (!files.length) return <p className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500">本轮目录还没有文件（步骤尚未开始，或目录还没创建）。</p>
  return (
    <div className="space-y-2 text-xs">
      {truncated && <p className="text-amber-700">文件太多，只列出了前 3,000 个。</p>}
      {[...groups.entries()].map(([top, items]) => (
        <details key={top} open={top === '（本轮根目录）' || items.length <= 12} className="rounded-lg border border-slate-200 bg-white">
          <summary className="cursor-pointer px-3 py-1.5 font-medium">
            {top} <span className="font-normal text-slate-400">{items.length} 个文件</span>
          </summary>
          <ul className="border-t border-slate-100 py-1">
            {items.map((f) => (
              <li key={f.path}>
                <button onClick={() => onOpen(f.path)} className="flex w-full items-center gap-2 px-3 py-0.5 text-left hover:bg-slate-50" title={f.path}>
                  <span className="w-20 shrink-0 text-[10.5px] text-slate-500">{KIND_LABEL[f.kind] ?? f.kind}</span>
                  <span className="min-w-0 flex-1 truncate">{top === '（本轮根目录）' ? f.rel : f.rel.slice(top.length + 1)}</span>
                  <span className="tabular shrink-0 text-[10.5px] text-slate-400">{fmtBytes(f.size)}</span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      ))}
    </div>
  )
}
