import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Play } from 'lucide-react'
import { api } from '../../api'
import VirtualTable from '../../components/VirtualTable'
import type { DataColumn } from '../../types'

export default function SqlView({ pid, path, columns }: { pid: string; path: string; columns: DataColumn[] }) {
  const first = columns[0]?.name
  const [sql, setSql] = useState(
    first ? `SELECT "${first}", count(*) AS 行数\nFROM data\nGROUP BY 1\nORDER BY 行数 DESC\nLIMIT 50` : 'SELECT * FROM data LIMIT 100',
  )
  const run = useMutation({ mutationFn: () => api.sql(pid, path, sql) })
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-slate-500">
        只读查询：表名固定为 <code className="rounded bg-slate-100 px-1">data</code>，只允许一条 SELECT / WITH 语句，不能读写其他文件；最多返回 1,000 行，超过 20 秒自动中止。
      </p>
      <textarea
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') run.mutate()
        }}
        spellCheck={false}
        aria-label="SQL"
        className="h-32 w-full rounded-md border border-slate-300 p-2 font-mono text-xs outline-none focus:border-blue-500"
      />
      <button
        onClick={() => run.mutate()}
        disabled={run.isPending}
        className="inline-flex items-center gap-1 rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        <Play className="h-3 w-3" aria-hidden />
        {run.isPending ? '查询中…' : '运行（Ctrl+Enter）'}
      </button>
      {run.error && <p className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700">{(run.error as Error).message}</p>}
      {run.data && (
        <>
          <p className="text-[11px] text-slate-600">
            返回 {run.data.rows.length} 行{run.data.truncated ? '（已截断到前 1,000 行）' : ''}
          </p>
          <VirtualTable
            columns={run.data.columns}
            count={run.data.rows.length}
            getRow={(i) => run.data!.rows[i]}
            rowLabel={(i) => String(i + 1)}
            rowHeader="序号"
            height={420}
          />
        </>
      )}
    </div>
  )
}
