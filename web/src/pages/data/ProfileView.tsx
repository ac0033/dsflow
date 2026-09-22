import { Fragment, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { api } from '../../api'
import { BarChart, MiniBars, RatioBar } from '../../components/charts'
import JobProgress from '../../components/JobProgress'
import { binsFor } from '../../lib/bins'
import { fmtCell, fmtInt, fmtNum, fmtPct } from '../../lib/format'
import { useJob } from '../../lib/useJob'
import type { ColumnProfile, Profile } from '../../types'

const KIND_LABEL: Record<string, string> = { numeric: '数值', temporal: '时间', text: '文本', boolean: '布尔', other: '其他' }

export default function ProfileView({ pid, path }: { pid: string; path: string }) {
  const qc = useQueryClient()
  const profile = useQuery({ queryKey: ['profile', pid, path], queryFn: () => api.profile(pid, path) })
  const job = useJob<Profile>(() => qc.invalidateQueries({ queryKey: ['profile', pid, path] }))
  if (profile.isLoading) return <p className="text-sm text-slate-500">读取画像…</p>
  if (!profile.data) {
    return (
      <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-4 text-sm">
        <p>还没有画像。画像把整张表压缩成逐列指标（缺失、范围、分布、取值排行），结果按文件内容缓存，内容不变就不用重算。</p>
        <button
          disabled={job.running}
          onClick={async () => job.start(await api.makeProfile(pid, path))}
          className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {job.running ? '生成中…' : '生成画像'}
        </button>
        <JobProgress job={job.job} />
      </div>
    )
  }
  return <ProfileReport profile={profile.data} />
}

function listNames(cols: ColumnProfile[], value: (c: ColumnProfile) => string, limit = 3): string {
  const head = cols.slice(0, limit).map((c) => `${c.name}（${value(c)}）`)
  return head.join('、') + (cols.length > limit ? ` 等 ${cols.length} 列` : '')
}

export function ProfileReport({ profile }: { profile: Profile }) {
  const [q, setQ] = useState('')
  const [only, setOnly] = useState<'all' | 'missing' | 'numeric' | 'temporal' | 'text'>('all')
  const [open, setOpen] = useState<string | null>(null)
  const missing = useMemo(() => profile.columns.filter((c) => c.null_count > 0).sort((a, b) => b.null_rate - a.null_rate), [profile])
  const negative = profile.columns.filter((c) => (c.negative ?? 0) > 0)
  const blank = profile.columns.filter((c) => (c.blank ?? 0) > 0)
  const shown = profile.columns.filter(
    (c) =>
      c.name.toLowerCase().includes(q.toLowerCase()) &&
      (only === 'all' || (only === 'missing' ? c.null_count > 0 : c.kind === only)),
  )

  return (
    <div className="space-y-3">
      <section className="rounded-lg border border-slate-200 bg-white p-3 text-sm leading-relaxed">
        <p className="font-medium">
          {fmtInt(profile.rows)} 行 × {profile.column_count} 列。
          {missing.length ? `${missing.length} 列有缺失，缺得最多的是 ${listNames(missing, (c) => fmtPct(c.null_rate))}。` : '所有列都没有缺失。'}
        </p>
        {negative.length > 0 && <p>含负值的数值列：{listNames(negative, (c) => `${fmtInt(c.negative)} 行`)}。</p>}
        {blank.length > 0 && <p>含空白字符串（不是缺失，而是填了空格或空串）的文本列：{listNames(blank, (c) => `${fmtInt(c.blank)} 行`)}。</p>}
        <p className="mt-1 text-[11px] text-slate-500">
          画像生成于 {profile.generated_at.replace('T', ' ')}，耗时 {profile.seconds} 秒。缺失、负值、空白是精确计数；"不同值"是近似值（误差约 2%）。
        </p>
      </section>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索列名" aria-label="搜索列名" className="rounded border border-slate-300 px-2 py-1" />
        {(
          [
            ['all', '全部'],
            ['missing', '有缺失'],
            ['numeric', '数值'],
            ['temporal', '时间'],
            ['text', '文本'],
          ] as const
        ).map(([k, label]) => (
          <button key={k} onClick={() => setOnly(k)} className={`rounded-full px-2 py-0.5 ${only === k ? 'bg-slate-800 text-white' : 'bg-white ring-1 ring-slate-300 hover:bg-slate-50'}`}>
            {label}
          </button>
        ))}
        <span className="text-slate-500">
          显示 {shown.length} / {profile.column_count} 列，点击一行看详情
        </span>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-left text-[11px] text-slate-500">
            <tr>
              <th className="px-2 py-1.5 font-normal">列</th>
              <th className="px-2 py-1.5 font-normal">缺失</th>
              <th className="px-2 py-1.5 text-right font-normal">不同值（约）</th>
              <th className="px-2 py-1.5 font-normal">分布</th>
              <th className="px-2 py-1.5 font-normal">摘要</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((c) => (
              <Fragment key={c.name}>
                <tr onClick={() => setOpen(open === c.name ? null : c.name)} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" aria-expanded={open === c.name}>
                  <td className="whitespace-nowrap px-2 py-1.5">
                    <div className="flex items-center gap-1">
                      <ChevronRight className={`h-3 w-3 shrink-0 text-slate-400 transition-transform ${open === c.name ? 'rotate-90' : ''}`} aria-hidden />
                      <span className="font-medium">{c.name}</span>
                      <span className="rounded bg-slate-100 px-1 text-[10px] text-slate-500">{KIND_LABEL[c.kind]}</span>
                    </div>
                  </td>
                  <td className="tabular whitespace-nowrap px-2 py-1.5">
                    {c.null_count ? (
                      <span className="inline-flex items-center gap-1.5">
                        <RatioBar value={c.null_rate} width={48} />
                        {fmtPct(c.null_rate)}
                        <span className="text-slate-400">{fmtInt(c.null_count)}</span>
                      </span>
                    ) : (
                      <span className="text-slate-400">无</span>
                    )}
                  </td>
                  <td className="tabular px-2 py-1.5 text-right">{fmtInt(c.distinct_approx)}</td>
                  <td className="px-2 py-1">
                    <Mini c={c} />
                  </td>
                  <td className="max-w-[360px] truncate px-2 py-1.5 text-slate-600">
                    <Summary c={c} />
                  </td>
                </tr>
                {open === c.name && (
                  <tr className="border-t border-slate-100 bg-slate-50/60">
                    <td colSpan={5} className="px-3 py-3">
                      <ColumnDetail c={c} rows={profile.rows} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Mini({ c }: { c: ColumnProfile }) {
  if (c.histogram) return <MiniBars values={binsFor(c.histogram.edges, [c.histogram]).values[0]} label={`${c.name} 的取值分布`} />
  if (c.periods?.length) return <MiniBars values={c.periods.map((p) => p.count)} label={`${c.name} 按月的行数`} />
  if (c.top?.length) return <MiniBars values={c.top.map((t) => t.count)} label={`${c.name} 最常见的取值`} width={Math.min(120, c.top.length * 12)} />
  return null
}

function Summary({ c }: { c: ColumnProfile }) {
  if (c.kind === 'numeric') return <>范围 {fmtNum(c.min as number)} ~ {fmtNum(c.max as number)}，中位数 {fmtNum(c.q50)}</>
  if (c.kind === 'temporal') return <>从 {fmtCell(c.min)} 到 {fmtCell(c.max)}</>
  if (c.top?.length) return <>最常见：{fmtCell(c.top[0].value)}（{fmtInt(c.top[0].count)} 行）</>
  if (c.top_skipped) return <>几乎每行都不同（如编号、地址）</>
  return null
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] text-slate-500">{label}</dt>
      <dd className="tabular text-sm">{value}</dd>
    </div>
  )
}

function ColumnDetail({ c, rows }: { c: ColumnProfile; rows: number }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
      <dl className="grid grid-cols-2 content-start gap-x-4 gap-y-2">
        <Stat label="类型" value={c.type} />
        <Stat label="非空行数" value={fmtInt(c.non_null)} />
        <Stat label="缺失行数" value={`${fmtInt(c.null_count)}（${fmtPct(c.null_rate, 2)}）`} />
        <Stat label="不同值（约）" value={fmtInt(c.distinct_approx)} />
        {c.kind === 'numeric' && (
          <>
            <Stat label="最小 / 最大" value={`${fmtNum(c.min as number)} / ${fmtNum(c.max as number)}`} />
            <Stat label="均值 ± 标准差" value={`${fmtNum(c.mean)} ± ${fmtNum(c.std)}`} />
            <Stat label="四分位（25/50/75%）" value={`${fmtNum(c.q25)} / ${fmtNum(c.q50)} / ${fmtNum(c.q75)}`} />
            <Stat label="负值 / 零值" value={`${fmtInt(c.negative)} / ${fmtInt(c.zero)} 行`} />
          </>
        )}
        {c.kind === 'temporal' && <Stat label="起止" value={`${fmtCell(c.min)} ~ ${fmtCell(c.max)}`} />}
        {c.blank != null && <Stat label="空白字符串" value={`${fmtInt(c.blank)} 行`} />}
      </dl>
      <div className="min-w-0">
        {c.histogram && <Histogram c={c} />}
        {c.periods && c.periods.length > 0 && (
          <BarChart
            labels={c.periods.map((p) => p.label)}
            series={[{ name: '行数', values: c.periods.map((p) => p.count) }]}
            caption={`${c.name}：每个时间段有多少行`}
          />
        )}
        {c.top && c.top.length > 0 && <TopValues c={c} rows={rows} />}
        {c.top_skipped && <p className="text-xs text-slate-500">{c.top_skipped}</p>}
      </div>
    </div>
  )
}

function Histogram({ c }: { c: ColumnProfile }) {
  const bins = binsFor(c.histogram!.edges, [c.histogram!])
  return (
    <BarChart
      labels={bins.labels}
      series={[{ name: '行数', values: bins.values[0] }]}
      describe={bins.describe}
      caption={`${c.name}：各区间有多少行（不含缺失）。${bins.note}`}
    />
  )
}

function TopValues({ c, rows }: { c: ColumnProfile; rows: number }) {
  const max = Math.max(...c.top!.map((t) => t.count))
  return (
    <figure className="m-0">
      <table className="w-full text-xs">
        <tbody>
          {c.top!.map((t, i) => (
            <tr key={i}>
              <td className="max-w-[240px] truncate py-0.5 pr-2" title={fmtCell(t.value)}>
                {t.value === '' ? <span className="text-slate-400">（空白）</span> : fmtCell(t.value)}
              </td>
              <td className="w-1/2 py-0.5">
                <span className="block h-2.5 rounded-r bg-[var(--viz-series-1)]" style={{ width: `${(t.count / max) * 100}%` }} />
              </td>
              <td className="tabular whitespace-nowrap py-0.5 pl-2 text-right">
                {fmtInt(t.count)} <span className="text-slate-400">{fmtPct(t.count / rows)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <figcaption className="mt-1 text-[11px] text-slate-500">{c.name}：最常见的 {c.top!.length} 个取值及行数（占全部行的比例）</figcaption>
    </figure>
  )
}
