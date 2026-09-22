import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Database, FileSpreadsheet, Search } from 'lucide-react'
import { api } from '../../api'
import JobProgress from '../../components/JobProgress'
import { fmtBytes, fmtInt } from '../../lib/format'
import { useJob } from '../../lib/useJob'
import type { DataFile, DataOverview } from '../../types'
import BrowseView from './BrowseView'
import ProfileView from './ProfileView'
import RegisterForm from './RegisterForm'
import SqlView from './SqlView'

/*
 * 数据文件：左边按分组索引，右边看选中的那个文件（浏览 / 画像 / SQL）。
 *
 * 同一份文件清单在两处用同一套分组：项目总览只列不属于任何阶段的文件（原始数据这类全项目共用的），
 * 阶段页列本阶段的文件（含各步骤产出的中间文件），分组标签由调用方给（总览按目录，阶段页按步骤）。
 */

export interface FileGroup {
  key: string
  label: string
  /** 分组标题后面的小字：目录、说明 */
  note?: string
}

/** 默认分组：按所在目录。 */
export const byDir = (f: DataFile): FileGroup => {
  const dir = f.path.includes('/') ? f.path.slice(0, f.path.lastIndexOf('/')) : '（项目根目录）'
  return { key: dir, label: dir }
}

export default function FilesTab({ pid, overview, files, path, onSelect, groupOf = byDir, note }: {
  pid: string
  overview: DataOverview
  /** 这一页要列的文件；不给就列全项目的 */
  files?: DataFile[]
  path: string | null
  onSelect: (path: string) => void
  groupOf?: (f: DataFile) => FileGroup
  /** 清单上方的一句话：这一页列的是哪些文件 */
  note?: string
}) {
  const shown = files ?? overview.files
  const file = shown.find((f) => f.path === path) ?? overview.files.find((f) => f.path === path) ?? null
  return (
    <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
      <FileList files={shown} selected={path} onSelect={onSelect} groupOf={groupOf} note={note} />
      {file ? (
        <FileView key={file.path} pid={pid} file={file} overview={overview} />
      ) : (
        <div className="rounded-lg border border-dashed border-slate-300 p-8 text-sm text-slate-500">
          从左侧选一个数据文件。支持 CSV / TSV / XLSX / Parquet；CSV 和 XLSX 首次查看时会转换成 Parquet 缓存，之后翻页、画像都读缓存。
        </div>
      )}
    </div>
  )
}

function FileList({ files, selected, onSelect, groupOf, note }: {
  files: DataFile[]
  selected: string | null
  onSelect: (p: string) => void
  groupOf: (f: DataFile) => FileGroup
  note?: string
}) {
  const [q, setQ] = useState('')
  const [onlyRegistered, setOnlyRegistered] = useState(false)
  const [shut, setShut] = useState<Set<string>>(new Set())
  const registered = files.filter((f) => f.registered).length
  const groups = useMemo(() => {
    const want = q.trim().toLowerCase()
    const shown = files.filter((f) => f.path.toLowerCase().includes(want) && (!onlyRegistered || f.registered))
    const map = new Map<string, { group: FileGroup; items: DataFile[]; bytes: number }>()
    for (const f of shown) {
      const group = groupOf(f)
      const row = map.get(group.key) ?? { group, items: [], bytes: 0 }
      row.items.push(f)
      row.bytes += f.size
      map.set(group.key, row)
    }
    return [...map.values()].sort((a, b) => a.group.key.localeCompare(b.group.key))
  }, [files, q, onlyRegistered, groupOf])
  const total = groups.reduce((n, g) => n + g.items.length, 0)

  return (
    <aside className="flex max-h-[calc(100vh-190px)] flex-col rounded-lg border border-slate-200 bg-white">
      <div className="space-y-1.5 border-b border-slate-200 p-2">
        {note && <p className="px-0.5 text-[11px] leading-relaxed text-slate-500">{note}</p>}
        <label className="flex items-center gap-1.5 rounded border border-slate-300 px-2 py-1">
          <Search className="h-3.5 w-3.5 text-slate-400" aria-hidden />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`在 ${files.length} 个数据文件中搜索`} className="w-full text-xs outline-none" />
        </label>
        <div className="flex items-center gap-2 px-0.5 text-[11px] text-slate-500">
          <label className="inline-flex items-center gap-1">
            <input type="checkbox" checked={onlyRegistered} onChange={(e) => setOnlyRegistered(e.target.checked)} />
            只看已登记的数据集（{registered}）
          </label>
          <span className="ml-auto tabular">列出 {total} 个</span>
        </div>
      </div>
      <div className="overflow-auto p-1.5">
        {groups.map(({ group, items, bytes }) => {
          const closed = shut.has(group.key)
          return (
            <section key={group.key} className="mb-1.5">
              <button
                type="button"
                onClick={() => setShut((now) => {
                  const next = new Set(now)
                  next.has(group.key) ? next.delete(group.key) : next.add(group.key)
                  return next
                })}
                className="sticky top-0 flex w-full items-start gap-1 rounded bg-slate-50 px-1.5 py-1 text-left text-[11px] text-slate-600 hover:bg-slate-100"
                title={group.note ? `${group.label}（${group.note}）` : group.label}
              >
                {closed ? <ChevronRight className="mt-0.5 h-3 w-3 shrink-0" aria-hidden /> : <ChevronDown className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />}
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-1">
                    <span className="min-w-0 flex-1 truncate font-medium text-slate-700">{group.label}</span>
                    <span className="tabular shrink-0 text-slate-400">{items.length} 个 · {fmtBytes(bytes)}</span>
                  </span>
                  {group.note && <span className="block truncate text-[10px] text-slate-400">{group.note}</span>}
                </span>
              </button>
              {!closed &&
                items.map((f) => (
                  <button
                    key={f.path}
                    onClick={() => onSelect(f.path)}
                    className={`flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-xs ${selected === f.path ? 'bg-blue-50 text-blue-800' : 'hover:bg-slate-100'}`}
                    title={f.path}
                  >
                    {f.registered ? <Database className="h-3.5 w-3.5 shrink-0 text-blue-600" aria-label="已登记" /> : <FileSpreadsheet className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />}
                    <span className="min-w-0 flex-1 truncate">{f.path.split('/').pop()}</span>
                    {f.dataset && f.data_stage && <span className="shrink-0 rounded bg-blue-50 px-1 text-[10px] text-blue-700">{STAGE_TEXT[f.data_stage] ?? f.data_stage}</span>}
                    <span className="shrink-0 text-[10px] uppercase text-slate-400">{f.format}</span>
                    <span className="tabular w-14 shrink-0 text-right text-[10px] text-slate-400">{fmtBytes(f.size)}</span>
                    <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${f.ready ? 'bg-green-600' : 'bg-slate-300'}`} title={f.ready ? '可直接浏览' : '需先转换'} />
                  </button>
                ))}
            </section>
          )
        })}
        {!groups.length && <p className="p-2 text-xs text-slate-400">没有匹配的文件</p>}
      </div>
    </aside>
  )
}

/** 登记数据集时写的数据阶段，和登记表里用的是同一套说法。 */
const STAGE_TEXT: Record<string, string> = {
  raw: '原始', processed: '处理后', features: '特征', splits: '划分',
  model_input: '建模输入', predictions: '预测结果', other: '其他',
}

function FileView({ pid, file, overview }: { pid: string; file: DataFile; overview: DataOverview }) {
  const qc = useQueryClient()
  const meta = useQuery({ queryKey: ['meta', pid, file.path], queryFn: () => api.meta(pid, file.path) })
  const [view, setView] = useState<'browse' | 'profile' | 'sql'>('browse')
  const [registering, setRegistering] = useState(false)
  const prep = useJob(() => {
    qc.invalidateQueries({ queryKey: ['meta', pid, file.path] })
    qc.invalidateQueries({ queryKey: ['data', pid] })
  })
  const dataset = overview.datasets.find((d) => d.versions.some((v) => v.path === file.path))
  const conv = meta.data?.conversion as
    | { reader?: string; encoding?: string; seconds?: number; text_columns?: string[]; source_format?: string }
    | null
  const how = conv?.reader === 'stream' ? '逐行流式解析' : conv?.reader === 'duckdb-excel' ? 'DuckDB 直接读取' : conv?.encoding ? `编码 ${conv.encoding}` : ''

  return (
    <section className="min-w-0 space-y-3">
      <div className="rounded-lg border border-slate-200 bg-white p-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="break-all text-sm font-semibold">{file.path}</h2>
          <span className="rounded bg-slate-100 px-1.5 text-[11px] uppercase text-slate-600">{file.format}</span>
          <span className="text-[11px] text-slate-500">{fmtBytes(file.size)}</span>
          {meta.data?.ready && (
            <span className="tabular text-[11px] text-slate-700">
              {fmtInt(meta.data.rows)} 行 × {meta.data.columns?.length} 列
            </span>
          )}
          {dataset ? (
            <span className="rounded bg-blue-50 px-1.5 text-[11px] text-blue-700">数据集 {dataset.name}</span>
          ) : (
            <button onClick={() => setRegistering(!registering)} className="ml-auto rounded border border-slate-300 px-2 py-0.5 text-[11px] hover:bg-slate-50">
              登记为数据集
            </button>
          )}
        </div>
        {conv && (
          <p className="mt-1 text-[11px] text-slate-500">
            由 {conv.source_format?.toUpperCase()} 转换缓存（{how ? `${how}，` : ''}用时 {conv.seconds} 秒）
            {conv.text_columns?.length ? `；${conv.text_columns.length} 列因含非数字 / 非日期内容保留为文本` : ''}
          </p>
        )}
        {registering && (
          <div className="mt-3 border-t border-slate-100 pt-3">
            <RegisterForm pid={pid} overview={overview} initialPath={file.path} onDone={() => setRegistering(false)} />
          </div>
        )}
      </div>

      {meta.data && !meta.data.ready && (
        <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-4 text-sm">
          <p>
            这个 {file.format.toUpperCase()} 文件还没有转换。转换一次（按内容哈希缓存，原文件不动）之后，翻页、筛选、画像都直接读缓存。
            {file.size > 50 << 20 && ' 文件较大，转换可能需要几分钟，可以先去看别的文件。'}
          </p>
          <button
            disabled={prep.running}
            onClick={async () => prep.start(await api.prepare(pid, file.path))}
            className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {prep.running ? '转换中…' : '转换为 Parquet'}
          </button>
          <JobProgress job={prep.job} />
        </div>
      )}

      {meta.data?.ready && (
        <>
          <div className="flex gap-1 border-b border-slate-200" role="tablist">
            {(
              [
                ['browse', '浏览'],
                ['profile', '画像'],
                ['sql', 'SQL 查询'],
              ] as const
            ).map(([v, label]) => (
              <button
                key={v}
                role="tab"
                aria-selected={view === v}
                onClick={() => setView(v)}
                className={`-mb-px border-b-2 px-3 py-1.5 text-xs ${view === v ? 'border-blue-600 font-medium text-blue-700' : 'border-transparent text-slate-600 hover:text-slate-900'}`}
              >
                {label}
              </button>
            ))}
          </div>
          {view === 'browse' && <BrowseView pid={pid} path={file.path} columns={meta.data.columns ?? []} />}
          {view === 'profile' && <ProfileView pid={pid} path={file.path} />}
          {view === 'sql' && <SqlView pid={pid} path={file.path} columns={meta.data.columns ?? []} />}
        </>
      )}
    </section>
  )
}
