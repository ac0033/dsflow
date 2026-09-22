import { Fragment, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, ChevronRight, Plus, Trash2, XCircle } from 'lucide-react'
import { api } from '../../api'
import { BarChart, DeltaBar } from '../../components/charts'
import ColumnPicker from '../../components/ColumnPicker'
import JobProgress from '../../components/JobProgress'
import { binsFor } from '../../lib/bins'
import { fmtCell, fmtInt, fmtNum, fmtPct, fmtSigned, fmtSignedPct } from '../../lib/format'
import { useJob } from '../../lib/useJob'
import type { CheckResult, CheckSpec, CheckType, CompareResult, DataOverview } from '../../types'

export default function CompareTab({ pid, overview }: { pid: string; overview: DataOverview }) {
  // 可以从运行详情的"完整对比"带着 ?a=&b= 进来
  const [params] = useSearchParams()
  const [a, setA] = useState(params.get('a') ?? '')
  const [b, setB] = useState(params.get('b') ?? '')
  const [key, setKey] = useState<string[]>([])
  const [segment, setSegment] = useState<string[]>([])
  const [result, setResult] = useState<CompareResult | null>(null)
  const job = useJob<CompareResult>(setResult)
  const metaA = useQuery({ queryKey: ['meta', pid, a], queryFn: () => api.meta(pid, a), enabled: !!a })
  const metaB = useQuery({ queryKey: ['meta', pid, b], queryFn: () => api.meta(pid, b), enabled: !!b })
  const common = useMemo(() => {
    const nb = new Set(metaB.data?.columns?.map((c) => c.name))
    return (metaA.data?.columns ?? []).map((c) => c.name).filter((n) => nb.has(n))
  }, [metaA.data, metaB.data])
  const bothReady = !!metaA.data?.ready && !!metaB.data?.ready

  return (
    <div className="space-y-4">
      <section className="space-y-2 rounded-lg border border-slate-200 bg-white p-3 text-xs">
        <div className="grid gap-2 md:grid-cols-2">
          <FilePick label="A（处理前 / 旧版本）" value={a} onChange={setA} overview={overview} />
          <FilePick label="B（处理后 / 新版本）" value={b} onChange={setB} overview={overview} />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-1.5">
            <span className="text-slate-500">主键（可选，按它逐行对齐）</span>
            <ColumnPicker label="主键列" options={common} value={key} onChange={setKey} placeholder={bothReady ? '不按主键对齐' : '两边都转换后可选'} />
          </label>
          <label className="flex items-center gap-1.5">
            <span className="text-slate-500">分组列（可选，看变化集中在哪一组）</span>
            <ColumnPicker label="分组列" options={common} value={segment} onChange={setSegment} multiple={false} placeholder={bothReady ? '不分组' : '两边都转换后可选'} />
          </label>
          <button
            disabled={!a || !b || a === b || job.running}
            onClick={async () => {
              setResult(null)
              job.start(await api.compare(pid, { a, b, key, segment: segment[0] ?? null }))
            }}
            className="ml-auto rounded bg-blue-600 px-3 py-1.5 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {job.running ? '对比中…' : '开始对比'}
          </button>
        </div>
        {!bothReady && a && b && <p className="text-[11px] text-slate-500">未转换的文件会在对比时自动转换并生成画像；完成后可再选主键和分组列重新对比。</p>}
        <JobProgress job={job.job} />
      </section>
      {result && <CompareReport pid={pid} r={result} common={common} />}
    </div>
  )
}

function FilePick({ label, value, onChange, overview }: { label: string; value: string; onChange: (v: string) => void; overview: DataOverview }) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-slate-500">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded border border-slate-300 bg-white px-2 py-1">
        <option value="">选择数据文件</option>
        {overview.datasets.length > 0 && (
          <optgroup label="已登记数据集">
            {overview.datasets.flatMap((d) =>
              d.versions.map((v) => (
                <option key={`${d.name}-${v.version}`} value={v.path}>
                  {d.name} · {v.version}（{v.path}）
                </option>
              )),
            )}
          </optgroup>
        )}
        <optgroup label="项目中的数据文件">
          {overview.files.map((f) => (
            <option key={f.path} value={f.path}>
              {f.path}
            </option>
          ))}
        </optgroup>
      </select>
    </label>
  )
}

function Section({ title, children, note }: { title: string; children: React.ReactNode; note?: string }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-3">
      <h3 className="text-sm font-semibold">{title}</h3>
      {note && <p className="mb-2 mt-0.5 text-[11px] text-slate-500">{note}</p>}
      <div className={note ? '' : 'mt-2'}>{children}</div>
    </section>
  )
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-md border border-slate-200 px-3 py-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
    </div>
  )
}

export function CompareReport({ pid, r, common }: { pid: string; r: CompareResult; common: string[] }) {
  const s = r.schema
  const k = r.key
  const seg = r.segment
  return (
    <div className="space-y-3">
      <section className="rounded-lg border border-blue-200 bg-blue-50/60 p-3 text-sm leading-relaxed">
        <p className="font-medium">
          行数 {fmtInt(r.rows.a)} → {fmtInt(r.rows.b)}（{r.rows.delta === 0 ? '不变' : `${fmtSigned(r.rows.delta)}，${fmtSignedPct(r.rows.pct)}`}）；列数 {r.column_count.a} → {r.column_count.b}
          {s.added.length ? `，新增 ${s.added.length} 列` : ''}
          {s.removed.length ? `，删除 ${s.removed.length} 列` : ''}
          {s.type_changed.length ? `，${s.type_changed.length} 列类型改变` : ''}。共同列中 {r.changed_columns} 列的统计量有变化。
        </p>
        {k && (
          <p>
            按「{k.keys.join('、')}」对齐：两边都有 {fmtInt(k.matched)} 个；只在 A {fmtInt(k.only_a)} 个（处理后消失）；只在 B {fmtInt(k.only_b)} 个（新出现）
            {k.changed_rows != null ? `；两边都有的行中 ${fmtInt(k.changed_rows)} 行至少一列取值改变。` : '。'}
          </p>
        )}
        {seg && seg.concentrated.length > 0 && (
          <p className="mt-1 flex items-start gap-1 text-amber-900">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span>
              变化集中在「{seg.column}」={seg.concentrated.join('、')}：
              {seg.rows
                .filter((x) => seg.concentrated.includes(x.value))
                .map((x) => `${x.value} 占全部${x.delta < 0 ? '减少' : '增加'}行数的 ${fmtPct(x.share_of_change)}，而在 A 中只占 ${fmtPct(x.share_a)}`)
                .join('；')}
              。处理可能不是均匀地作用在各组上，需要确认是否合理。
            </span>
          </p>
        )}
        <p className="mt-1 text-[11px] text-slate-500">
          A = {r.a}；B = {r.b}
        </p>
      </section>

      {(s.added.length > 0 || s.removed.length > 0 || s.type_changed.length > 0) && (
        <Section title="结构变化">
          <div className="space-y-1 text-xs">
            {s.added.length > 0 && <p>新增列：{s.added.join('、')}</p>}
            {s.removed.length > 0 && <p>删除列：{s.removed.join('、')}</p>}
            {s.type_changed.map((t) => (
              <p key={t.name}>
                类型改变：{t.name}（{t.a} → {t.b}）
              </p>
            ))}
          </div>
        </Section>
      )}

      {k && (
        <Section title={`按主键对齐：${k.keys.join('、')}`} note="只在 A = 处理后找不到这个主键；只在 B = 处理后新出现；取值改变 = 两边都有，但至少一列的值不同（数值按相对误差 1e-9 判断）。">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Tile label="两边都有" value={fmtInt(k.matched)} />
            <Tile label="只在 A（消失）" value={fmtInt(k.only_a)} />
            <Tile label="只在 B（新增）" value={fmtInt(k.only_b)} />
            <Tile label="取值改变的行" value={k.changed_rows != null ? fmtInt(k.changed_rows) : '—'} sub={k.changed_skipped} />
          </div>
          {(k.null_keys_a > 0 || k.null_keys_b > 0) && (
            <p className="mt-2 text-[11px] text-amber-800">
              主键为空的行无法对齐，没有参与上面的统计：A 有 {fmtInt(k.null_keys_a)} 行，B 有 {fmtInt(k.null_keys_b)} 行。
            </p>
          )}
          {(k.duplicates_a > 0 || k.duplicates_b > 0) && (
            <p className="mt-1 text-[11px] text-amber-800">
              主键不唯一（不含为空的行）：A 有 {fmtInt(k.duplicates_a)} 行与别的行主键相同，B 有 {fmtInt(k.duplicates_b)} 行。按这个主键逐行比对会把行数放大，所以没有统计逐列变化。
            </p>
          )}
          {k.changed_by_column && Object.keys(k.changed_by_column).length > 0 && (
            <div className="mt-3">
              <p className="mb-1 text-xs text-slate-600">各列有多少行取值改变</p>
              <HBars items={Object.entries(k.changed_by_column).sort((x, y) => y[1] - x[1])} />
            </div>
          )}
          <Samples k={k} />
        </Section>
      )}

      {seg && <SegmentSection seg={seg} />}

      <ColumnsSection pid={pid} r={r} />

      <ChecksPanel pid={pid} a={r.a} b={r.b} columns={common} />
    </div>
  )
}

function HBars({ items }: { items: [string, number][] }) {
  const max = Math.max(1, ...items.map((i) => i[1]))
  return (
    <table className="w-full text-xs">
      <tbody>
        {items.slice(0, 15).map(([name, n]) => (
          <tr key={name}>
            <td className="w-40 truncate py-0.5 pr-2">{name}</td>
            <td className="py-0.5">
              <span className="block h-2.5 rounded-r bg-[var(--viz-series-1)]" style={{ width: `${(n / max) * 100}%` }} />
            </td>
            <td className="tabular w-24 py-0.5 pl-2 text-right">{fmtInt(n)} 行</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Samples({ k }: { k: NonNullable<CompareResult['key']> }) {
  const blocks: [string, Record<string, unknown>[]][] = [
    ['只在 A 的行（样例）', k.sample_only_a],
    ['只在 B 的行（样例）', k.sample_only_b],
  ]
  return (
    <div className="mt-3 space-y-1 text-xs">
      {k.sample_changed && k.sample_changed.length > 0 && (
        <details>
          <summary className="cursor-pointer text-slate-600">取值改变的行（前 {k.sample_changed.length} 个样例）</summary>
          <ul className="mt-1 space-y-1">
            {k.sample_changed.map((s, i) => (
              <li key={i} className="rounded bg-slate-50 px-2 py-1">
                <span className="font-mono">{Object.entries(s.key).map(([c, v]) => `${c}=${fmtCell(v as never)}`).join('，')}</span>
                ：{s.changes.map((c) => `${c.column} ${fmtCell(c.a)} → ${fmtCell(c.b)}`).join('；')}
              </li>
            ))}
          </ul>
        </details>
      )}
      {blocks.map(([title, rows]) =>
        rows.length ? (
          <details key={title}>
            <summary className="cursor-pointer text-slate-600">{title}</summary>
            <div className="mt-1 max-h-56 overflow-auto">
              <table className="text-[11px]">
                <thead>
                  <tr>
                    {Object.keys(rows[0]).map((c) => (
                      <th key={c} className="whitespace-nowrap px-1.5 text-left font-normal text-slate-500">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i} className="border-t border-slate-100">
                      {Object.values(row).map((v, j) => (
                        <td key={j} className="max-w-[200px] truncate whitespace-nowrap px-1.5">
                          {fmtCell(v as never)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        ) : null,
      )}
    </div>
  )
}

function SegmentSection({ seg }: { seg: NonNullable<CompareResult['segment']> }) {
  const maxAbs = Math.max(1, ...seg.rows.map((r) => Math.abs(r.delta)))
  return (
    <Section
      title={`分组影响：${seg.column}`}
      note={`共 ${fmtInt(seg.groups)} 组；减少 ${fmtInt(seg.removed)} 行、增加 ${fmtInt(seg.added)} 行。"占全部变化"明显高于"在 A 中占比"的组，说明变化集中在它身上（标 ⚠）。`}
    >
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-[11px] text-slate-500">
            <tr>
              <th className="py-1 pr-2 font-normal">分组</th>
              <th className="py-1 pr-2 text-right font-normal">A 行数</th>
              <th className="py-1 pr-2 text-right font-normal">B 行数</th>
              <th className="py-1 pr-2 font-normal">变化</th>
              <th className="py-1 pr-2 text-right font-normal">变化率</th>
              <th className="py-1 pr-2 text-right font-normal">占全部变化</th>
              <th className="py-1 text-right font-normal">在 A 中占比</th>
            </tr>
          </thead>
          <tbody className="tabular">
            {seg.rows.map((r) => {
              const hot = seg.concentrated.includes(r.value)
              return (
                <tr key={r.value} className={`border-t border-slate-100 ${hot ? 'bg-amber-50' : ''}`}>
                  <td className="max-w-[220px] truncate py-1 pr-2" title={r.value}>
                    {hot && <span className="mr-1 text-amber-700">⚠ 集中</span>}
                    {r.value}
                  </td>
                  <td className="py-1 pr-2 text-right">{fmtInt(r.a)}</td>
                  <td className="py-1 pr-2 text-right">{fmtInt(r.b)}</td>
                  <td className="py-1 pr-2">
                    <span className="inline-flex items-center gap-1.5">
                      <DeltaBar value={r.delta} maxAbs={maxAbs} />
                      {fmtSigned(r.delta)}
                    </span>
                  </td>
                  <td className="py-1 pr-2 text-right">{fmtSignedPct(r.pct)}</td>
                  <td className="py-1 pr-2 text-right">{r.delta ? fmtPct(r.share_of_change) : '—'}</td>
                  <td className="py-1 text-right">{fmtPct(r.share_a)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {seg.other_groups > 0 && <p className="mt-1 text-[11px] text-slate-500">另有 {fmtInt(seg.other_groups)} 组变化较小，未列出。</p>}
    </Section>
  )
}

function ColumnsSection({ pid, r }: { pid: string; r: CompareResult }) {
  const [onlyChanged, setOnlyChanged] = useState(true)
  const [open, setOpen] = useState<string | null>(null)
  const rows = r.columns.filter((c) => !onlyChanged || c.flags.length)
  return (
    <Section title="逐列变化" note="基于两份画像比较：缺失数、不同值个数（近似）、均值与中位数。点一行，用同一组分箱看两版的分布。">
      <label className="mb-2 flex items-center gap-1.5 text-xs text-slate-600">
        <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />
        只看有变化的列（{r.changed_columns} / {r.columns.length}）
      </label>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-[11px] text-slate-500">
            <tr>
              <th className="py-1 pr-2 font-normal">列</th>
              <th className="py-1 pr-2 font-normal">缺失 A → B</th>
              <th className="py-1 pr-2 font-normal">不同值 A → B</th>
              <th className="py-1 pr-2 font-normal">均值 A → B</th>
              <th className="py-1 pr-2 font-normal">中位数 A → B</th>
              <th className="py-1 font-normal">变化</th>
            </tr>
          </thead>
          <tbody className="tabular">
            {rows.map((c) => (
              <Fragment key={c.name}>
                <tr onClick={() => setOpen(open === c.name ? null : c.name)} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" aria-expanded={open === c.name}>
                  <td className="py-1 pr-2">
                    <span className="inline-flex items-center gap-1">
                      <ChevronRight className={`h-3 w-3 text-slate-400 ${open === c.name ? 'rotate-90' : ''}`} aria-hidden />
                      {c.name}
                    </span>
                  </td>
                  <td className="py-1 pr-2">
                    {fmtInt(c.null_a)} → {fmtInt(c.null_b)}
                  </td>
                  <td className="py-1 pr-2">
                    {fmtInt(c.distinct_a)} → {fmtInt(c.distinct_b)}
                  </td>
                  <td className="py-1 pr-2">{c.mean_a !== undefined ? `${fmtNum(c.mean_a)} → ${fmtNum(c.mean_b)}` : '—'}</td>
                  <td className="py-1 pr-2">{c.q50_a !== undefined ? `${fmtNum(c.q50_a)} → ${fmtNum(c.q50_b)}` : '—'}</td>
                  <td className="py-1">
                    {c.flags.map((f) => (
                      <span key={f} className="mr-1 rounded bg-slate-100 px-1 text-[10px] text-slate-700">
                        {f}
                      </span>
                    ))}
                  </td>
                </tr>
                {open === c.name && (
                  <tr>
                    <td colSpan={6} className="bg-slate-50/60 px-2 py-2">
                      <DistributionPanel pid={pid} a={r.a} b={r.b} column={c.name} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  )
}

function DistributionPanel({ pid, a, b, column }: { pid: string; a: string; b: string; column: string }) {
  const d = useQuery({ queryKey: ['dist', pid, a, b, column], queryFn: () => api.distribution(pid, a, b, column) })
  if (d.isLoading) return <p className="text-xs text-slate-500">计算分布…</p>
  if (d.error) return <p className="text-xs text-red-600">{(d.error as Error).message}</p>
  const dist = d.data!
  if (dist.kind === 'numeric' && !dist.edges?.length) return <p className="text-xs text-slate-500">两版这一列都没有数值。</p>
  const bins =
    dist.kind === 'numeric'
      ? binsFor(dist.edges!, [
          { counts: dist.a, under: dist.under?.[0], over: dist.over?.[0] },
          { counts: dist.b, under: dist.under?.[1], over: dist.over?.[1] },
        ])
      : { labels: dist.labels!, values: [dist.a, dist.b], describe: (i: number) => dist.labels![i], note: '' }
  return (
    <BarChart
      labels={bins.labels}
      series={[
        { name: 'A 处理前', values: bins.values[0] },
        { name: 'B 处理后', values: bins.values[1] },
      ]}
      describe={bins.describe}
      caption={`${column}：两版用同一组${dist.kind === 'numeric' ? '区间' : dist.kind === 'temporal' ? '时间段' : '取值（前 12 个 + 其他）'}统计行数。${bins.note}`}
    />
  )
}

const CHECKS: { type: CheckType; label: string; needs: ('key' | 'columns' | 'column' | 'tolerance')[] }[] = [
  { type: 'row_count_equal', label: '行数不变', needs: [] },
  { type: 'row_count_max_change', label: '行数变化不超过容差（比例）', needs: ['tolerance'] },
  { type: 'sum_equal', label: '某列合计不变', needs: ['column', 'tolerance'] },
  { type: 'columns_unchanged', label: '按主键对齐后，这些列原值不变', needs: ['key', 'columns'] },
  { type: 'no_new_nulls', label: '这些列不新增缺失', needs: ['columns'] },
  { type: 'keys_preserved', label: '处理前的主键处理后都还在', needs: ['key'] },
]

function ChecksPanel({ pid, a, b, columns }: { pid: string; a: string; b: string; columns: string[] }) {
  const [checks, setChecks] = useState<CheckSpec[]>([{ type: 'row_count_equal', key: [], columns: [], column: null, tolerance: 0 }])
  const run = useMutation({ mutationFn: () => api.checks(pid, a, b, checks) })
  const patch = (i: number, p: Partial<CheckSpec>) => setChecks(checks.map((c, j) => (j === i ? { ...c, ...p } : c)))
  const results: CheckResult[] | undefined = run.data
  return (
    <Section title="不变量检查" note="声明「哪些东西必须不变」，在 A、B 两版上自动核对。结果只说明这两份数据满足或不满足这些条件，不代替业务判断。">
      <div className="space-y-2 text-xs">
        {checks.map((c, i) => {
          const spec = CHECKS.find((x) => x.type === c.type)!
          const res = results?.[i]
          return (
            <div key={i} className="flex flex-wrap items-center gap-2 rounded border border-slate-200 p-2">
              <select value={c.type} onChange={(e) => patch(i, { type: e.target.value as CheckType })} className="rounded border border-slate-300 bg-white px-1 py-1">
                {CHECKS.map((x) => (
                  <option key={x.type} value={x.type}>
                    {x.label}
                  </option>
                ))}
              </select>
              {spec.needs.includes('key') && <ColumnPicker label="主键" options={columns} value={c.key} onChange={(v) => patch(i, { key: v })} placeholder="主键" />}
              {spec.needs.includes('columns') && <ColumnPicker label="列" options={columns} value={c.columns} onChange={(v) => patch(i, { columns: v })} placeholder="要检查的列" />}
              {spec.needs.includes('column') && (
                <ColumnPicker label="合计列" options={columns} value={c.column ? [c.column] : []} onChange={(v) => patch(i, { column: v[0] ?? null })} multiple={false} placeholder="合计列" />
              )}
              {spec.needs.includes('tolerance') && (
                <label className="flex items-center gap-1">
                  容差
                  <input type="number" step="any" min={0} value={c.tolerance} onChange={(e) => patch(i, { tolerance: Number(e.target.value) })} className="w-20 rounded border border-slate-300 px-1 py-0.5" />
                </label>
              )}
              {res && (
                <span className="flex items-center gap-1">
                  {res.passed ? <CheckCircle2 className="h-4 w-4 text-[#0ca30c]" aria-hidden /> : <XCircle className="h-4 w-4 text-[#d03b3b]" aria-hidden />}
                  <b>{res.passed ? '通过' : '未通过'}</b>
                  <span className="text-slate-600">{res.detail}</span>
                </span>
              )}
              <button aria-label="删除这条检查" onClick={() => setChecks(checks.filter((_, j) => j !== i))} className="ml-auto text-slate-400 hover:text-slate-700">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          )
        })}
        <div className="flex items-center gap-2">
          <button onClick={() => setChecks([...checks, { type: 'columns_unchanged', key: [], columns: [], column: null, tolerance: 0 }])} className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 hover:bg-slate-50">
            <Plus className="h-3 w-3" aria-hidden />
            添加检查
          </button>
          <button onClick={() => run.mutate()} disabled={run.isPending || !checks.length} className="rounded bg-blue-600 px-3 py-1 font-medium text-white hover:bg-blue-700 disabled:opacity-50">
            {run.isPending ? '检查中…' : '运行检查'}
          </button>
          {results && (
            <span className="text-slate-600">
              {results.filter((x) => x.passed).length} / {results.length} 项通过
            </span>
          )}
          {run.error && <span className="text-red-600">{(run.error as Error).message}</span>}
        </div>
      </div>
    </Section>
  )
}
