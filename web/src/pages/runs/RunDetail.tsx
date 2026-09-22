import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Copy, RotateCw } from 'lucide-react'
import { api } from '../../api'
import { RunStatusBadge, ValidityBadge } from '../../components/RunBadges'
import { fmtDuration, fmtInt, fmtNum, fmtSigned, fmtTime } from '../../lib/format'
import type { RunDetail as RunDetailType } from '../../types'

function Box({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-3">
      <h3 className="mb-1.5 text-sm font-semibold">{title}</h3>
      {children}
    </section>
  )
}

/** 一次运行：先说为了验证什么、结论是什么，再给指标、数据变化、参数、复现方法和日志。 */
export default function RunDetail({ pid, runId }: { pid: string; runId: string }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const q = useQuery({ queryKey: ['run', pid, runId], queryFn: () => api.run(pid, runId), refetchInterval: (query) => (query.state.data?.status === 'running' ? 2000 : false) })
  const rerun = useMutation({
    mutationFn: () => api.rerun(pid, runId),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['runs', pid] })
      navigate(`/p/${pid}/runs/${r.run_id}`)
    },
  })
  if (q.isLoading) return <p className="text-sm text-slate-500">读取运行记录…</p>
  if (q.error) return <p className="text-sm text-red-600">{(q.error as Error).message}</p>
  const r = q.data!
  const rerunBlocked = r.readonly ? '只读接入的项目不能从平台重跑（会写入项目目录），请在命令行用 dsflow run 运行' : !r.argv.length ? '没有记录启动命令' : null
  const folds = Object.keys(r.fold_metrics)

  return (
    <div className="max-w-5xl space-y-3">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="font-mono text-sm font-semibold">{r.run_id}</h2>
        <RunStatusBadge status={r.status} />
        <ValidityBadge validity={r.validity} />
        <Link to={`/p/${pid}/steps/${r.step}`} className="text-xs text-blue-700 hover:underline">
          步骤 {r.step}
          {r.revision ? ` · ${r.revision}` : ''}
        </Link>
        <span className="text-xs text-slate-500">
          {fmtTime(r.started_at)} 开始，用时 {fmtDuration(r.duration_s)}
          {r.rerun_of && (
            <>
              ，重跑自{' '}
              <Link to={`/p/${pid}/runs/${r.rerun_of}`} className="font-mono text-blue-700 hover:underline">
                {r.rerun_of}
              </Link>
            </>
          )}
        </span>
        <button
          onClick={() => rerun.mutate()}
          disabled={!!rerunBlocked || rerun.isPending || r.status === 'running'}
          title={rerunBlocked ?? '用同样的命令再运行一次，生成一条新的运行记录'}
          className="ml-auto inline-flex items-center gap-1 rounded bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <RotateCw className="h-3 w-3" aria-hidden />
          一键重跑
        </button>
      </header>
      {rerunBlocked && <p className="text-[11px] text-slate-500">{rerunBlocked}</p>}
      {rerun.error && <p className="text-xs text-red-600">{(rerun.error as Error).message}</p>}

      <section className={`rounded-lg border p-3 ${r.status === 'failed' ? 'border-red-200 bg-red-50' : 'border-blue-200 bg-blue-50/60'}`}>
        <p className="text-xs text-slate-600">假设：{r.hypothesis || '没有记录'}</p>
        <p className="mt-1 text-base font-semibold leading-relaxed">{r.conclusion || (r.status === 'running' ? '运行中…' : '没有记录结论')}</p>
        {r.status === 'failed' && (
          <p className="mt-1 flex items-start gap-1 text-sm text-red-800">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            {r.error || '运行失败'}
            {r.exit_code != null && `（退出码 ${r.exit_code}）`}
          </p>
        )}
      </section>

      {(Object.keys(r.metrics).length > 0 || folds.length > 0) && (
        <Box title="指标">
          {Object.keys(r.metrics).length > 0 && (
            <table className="tabular text-sm">
              <tbody>
                {Object.entries(r.metrics).map(([k, v]) => (
                  <tr key={k}>
                    <td className="pr-4 text-slate-600">{k}</td>
                    <td className="font-semibold">{v == null ? '—（非有限数）' : fmtNum(v, 6)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {folds.length > 0 && (
            <div className="mt-2 overflow-x-auto">
              <p className="mb-1 text-xs text-slate-500">逐折结果（看结果随切分的波动）</p>
              <table className="tabular text-xs">
                <thead className="text-slate-500">
                  <tr>
                    <th className="pr-3 text-left font-normal">折</th>
                    {[...new Set(folds.flatMap((f) => Object.keys(r.fold_metrics[f])))].map((m) => (
                      <th key={m} className="pr-3 text-left font-normal">
                        {m}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {folds.map((f) => (
                    <tr key={f} className="border-t border-slate-100">
                      <td className="pr-3">{f}</td>
                      {[...new Set(folds.flatMap((x) => Object.keys(r.fold_metrics[x])))].map((m) => (
                        <td key={m} className="pr-3">
                          {r.fold_metrics[f][m] == null ? '—' : fmtNum(r.fold_metrics[f][m]!, 6)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Box>
      )}

      {(r.inputs.length > 0 || r.outputs.length > 0) && (
        <Box title="数据：输入 → 输出">
          <div className="grid gap-3 text-xs sm:grid-cols-2">
            {(
              [
                ['输入', r.inputs],
                ['输出', r.outputs],
              ] as const
            ).map(([label, refs]) => (
              <div key={label}>
                <p className="mb-1 text-slate-500">{label}</p>
                {refs.length ? (
                  <ul className="space-y-1">
                    {refs.map((d) => (
                      <li key={`${d.name}-${d.version}`}>
                        <Link to={`/p/${pid}/data?tab=files&path=${encodeURIComponent(d.path)}`} className="font-medium text-blue-700 hover:underline">
                          {d.name}
                        </Link>
                        <span className="ml-1 font-mono text-[10px] text-slate-400">{d.version}</span>
                        <span className="tabular ml-2 text-slate-600">{d.rows != null ? `${fmtInt(d.rows)} 行 × ${d.columns} 列` : ''}</span>
                        <div className="truncate text-[10.5px] text-slate-400" title={d.path}>
                          {d.path}
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-slate-400">没有登记</p>
                )}
              </div>
            ))}
          </div>
          {r.deltas.length > 0 && (
            <ul className="mt-3 space-y-1.5 border-t border-slate-100 pt-2 text-sm">
              {r.deltas.map((d, i) =>
                d.error ? (
                  <li key={i} className="text-xs text-amber-800">
                    {d.input ?? ''} → {d.output}：没能生成对比（{d.error}）
                  </li>
                ) : (
                  <li key={i}>
                    <b>{d.input}</b> → <b>{d.output}</b>：行数 {fmtInt(d.rows_a)} → {fmtInt(d.rows_b)}（{fmtSigned(d.row_delta)}）；列数 {d.columns_a} → {d.columns_b}
                    {d.added?.length ? `，新增 ${d.added.join('、')}` : ''}
                    {d.removed?.length ? `，删除 ${d.removed.join('、')}` : ''}；共同列中 {d.changed_columns} 列统计量有变化
                    {d.flagged?.length ? `（${d.flagged.slice(0, 5).join('、')}${d.flagged.length > 5 ? ' 等' : ''}）` : ''}。
                    <Link
                      to={`/p/${pid}/data?tab=compare&a=${encodeURIComponent(d.input_path ?? '')}&b=${encodeURIComponent(d.output_path ?? '')}`}
                      className="ml-1 text-xs text-blue-700 underline"
                    >
                      完整对比
                    </Link>
                  </li>
                ),
              )}
            </ul>
          )}
        </Box>
      )}

      {Object.keys(r.params).length > 0 && (
        <Box title="参数">
          <table className="text-sm">
            <tbody>
              {Object.entries(r.params).map(([k, v]) => (
                <tr key={k}>
                  <td className="pr-4 text-slate-600">{k}</td>
                  <td className="font-mono text-xs">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Box>
      )}

      {r.figures.length > 0 && (
        <Box title="图表">
          <div className="grid gap-3 sm:grid-cols-2">
            {r.figures.map((f) => (
              <figure key={f.file} className="m-0">
                <img src={`/api/projects/${pid}/runs/${r.run_id}/figure?file=${encodeURIComponent(f.file)}`} alt={f.name} className="max-w-full rounded border border-slate-200" />
                <figcaption className="mt-1 text-xs text-slate-500">{f.name}</figcaption>
              </figure>
            ))}
          </div>
        </Box>
      )}

      {r.artifacts.length > 0 && (
        <Box title="产物">
          <ul className="space-y-0.5 text-xs">
            {r.artifacts.map((a) => (
              <li key={a.path}>
                <span className="font-mono">{a.path}</span>
                <span className="ml-2 text-slate-600">{a.purpose}</span>
              </li>
            ))}
          </ul>
        </Box>
      )}

      {r.models && r.models.length > 0 && (
        <Box title="登记的模型">
          <ul className="space-y-0.5 text-xs">
            {r.models.map((m) => (
              <li key={`${m.name}-${m.version}`}>
                <Link to={`/p/${pid}/models/${encodeURIComponent(m.name)}/${m.version}`} className="font-medium text-blue-700 hover:underline">
                  {m.name}
                </Link>
                <span className="ml-1 font-mono text-[10px] text-slate-400">{m.version}</span>
                <span className="ml-2 font-mono text-slate-500">{m.path}</span>
              </li>
            ))}
          </ul>
        </Box>
      )}

      <Reproduce r={r} />

      <Box title="日志">
        <LogView pid={pid} run={r} onEnd={() => qc.invalidateQueries({ queryKey: ['run', pid, runId] })} />
      </Box>

      <details className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">
        <summary className="cursor-pointer font-medium">运行环境</summary>
        <dl className="mt-2 grid grid-cols-[8rem_1fr] gap-x-2 gap-y-0.5">
          <dt className="text-slate-500">命令</dt>
          <dd className="font-mono">{r.command || '—'}</dd>
          <dt className="text-slate-500">工作目录</dt>
          <dd className="font-mono">{r.cwd}</dd>
          <dt className="text-slate-500">代码版本</dt>
          <dd className="font-mono">
            {r.git_commit ?? '不是 git 仓库'}
            {r.git_dirty && <span className="ml-1 text-amber-700">（有未提交改动）</span>}
          </dd>
          {Object.entries(r.env).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-slate-500">{k.replace('pkg:', '')}</dt>
              <dd className="break-all font-mono">{v}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  )
}

function Reproduce({ r }: { r: RunDetailType }) {
  const [copied, setCopied] = useState(false)
  const text = r.reproduce.commands.join('\n')
  return (
    <Box title="复现卡片">
      <p className="mb-1 text-xs text-slate-500">在项目根目录依次执行：还原代码 → 还原依赖 → 核对输入数据哈希 → 重新运行。</p>
      <div className="relative">
        <pre className="overflow-x-auto rounded bg-slate-900 p-2 font-mono text-[11.5px] leading-relaxed text-slate-100">{text || '（没有可复现的命令）'}</pre>
        {text && (
          <button
            onClick={() => navigator.clipboard?.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })}
            className="absolute right-1.5 top-1.5 inline-flex items-center gap-1 rounded bg-slate-700 px-1.5 py-0.5 text-[10.5px] text-white"
          >
            <Copy className="h-3 w-3" aria-hidden />
            {copied ? '已复制' : '复制'}
          </button>
        )}
      </div>
      {r.reproduce.warnings.map((w) => (
        <p key={w} className="mt-1 flex items-start gap-1 text-xs text-amber-800">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
          {w}
        </p>
      ))}
    </Box>
  )
}

/** 日志：运行中用 SSE 实时追加，结束后读完整日志（过大时只显示最后 2 MB）。 */
function LogView({ pid, run, onEnd }: { pid: string; run: RunDetailType; onEnd: () => void }) {
  const [text, setText] = useState('')
  const [note, setNote] = useState('')
  const ref = useRef<HTMLPreElement>(null)
  const endRef = useRef(onEnd)
  endRef.current = onEnd
  useEffect(() => {
    setText('')
    setNote('')
    if (run.status === 'running') {
      const es = new EventSource(`/api/projects/${pid}/runs/${run.run_id}/stream`)
      es.onmessage = (e) => setText((t) => t + (JSON.parse(e.data) as { text: string }).text)
      es.addEventListener('end', () => {
        es.close()
        endRef.current()
      })
      es.onerror = () => es.close()
      return () => es.close()
    }
    api
      .runLog(pid, run.run_id)
      .then((l) => {
        setText(l.text)
        if (l.truncated) setNote(`日志共 ${fmtInt(l.size)} 字节，只显示最后 2 MB。`)
      })
      .catch((e: Error) => setNote(`读取日志失败：${e.message}`))
  }, [pid, run.run_id, run.status])
  useEffect(() => {
    ref.current?.scrollTo(0, ref.current.scrollHeight)
  }, [text])
  return (
    <>
      {note && <p className="mb-1 text-xs text-slate-500">{note}</p>}
      <pre ref={ref} className="max-h-80 overflow-auto rounded bg-slate-900 p-2 font-mono text-[11.5px] leading-relaxed text-slate-100" aria-live="polite">
        {text || (run.status === 'running' ? '等待输出…' : '（没有输出）')}
      </pre>
    </>
  )
}
