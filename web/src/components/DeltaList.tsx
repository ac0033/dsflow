import { Link } from 'react-router'
import { fmtInt, fmtSigned } from '../lib/format'
import type { RunDelta } from '../types'

/** 一次运行里"输入 → 输出"的变化摘要；每条可以打开完整对比（逐列统计、分布、分组影响）或浏览输出数据。 */
export default function DeltaList({ pid, deltas }: { pid: string; deltas: RunDelta[] }) {
  return (
    <ul className="space-y-1.5">
      {deltas.map((d, i) =>
        d.error ? (
          <li key={i} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            {d.input ?? ''} → {d.output}：没能生成对比（{d.error}）
          </li>
        ) : (
          <li key={i} className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm">
            <div>
              <b>{d.input}</b> → <b>{d.output}</b>
            </div>
            <div className="tabular mt-0.5 text-[13px] leading-relaxed text-slate-700">
              行数 {fmtInt(d.rows_a)} → {fmtInt(d.rows_b)}（{fmtSigned(d.row_delta)}）；列数 {d.columns_a} → {d.columns_b}
              {d.added?.length ? `，新增 ${d.added.join('、')}` : ''}
              {d.removed?.length ? `，删除 ${d.removed.join('、')}` : ''}；共同列中 {d.changed_columns} 列统计量有变化
              {d.flagged?.length ? `（${d.flagged.slice(0, 5).join('、')}${d.flagged.length > 5 ? ' 等' : ''}）` : ''}
            </div>
            <div className="mt-1 flex flex-wrap gap-3 text-xs">
              {d.input_path && d.output_path && (
                <Link
                  to={`/p/${pid}/data?tab=compare&a=${encodeURIComponent(d.input_path)}&b=${encodeURIComponent(d.output_path)}`}
                  className="text-blue-700 underline underline-offset-2"
                >
                  完整对比
                </Link>
              )}
              {d.output_path && (
                <Link to={`/p/${pid}/data?tab=files&path=${encodeURIComponent(d.output_path)}`} className="text-blue-700 underline underline-offset-2">
                  浏览输出数据
                </Link>
              )}
            </div>
          </li>
        ),
      )}
    </ul>
  )
}
