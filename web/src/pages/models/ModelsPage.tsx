import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Copy, FilePlus2, Lock, RefreshCw, XCircle } from 'lucide-react'
import { api } from '../../api'
import { inScope, stageKind, useScope } from '../../lib/scope'
import { ValidityBadge } from '../../components/RunBadges'
import { fmtBytes, fmtInt, fmtNum, fmtTime } from '../../lib/format'
import type { ChecklistReport, DeliveryChecklist, Gate, ModelDetail, ModelEntry, ModelStatus, ModelVersion } from '../../types'

const LABEL: Record<ModelStatus, string> = { candidate: '候选', accepted: '已验收', delivered: '已交付' }
const STYLE: Record<ModelStatus, string> = {
  candidate: 'bg-slate-100 text-slate-700',
  accepted: 'bg-sky-100 text-sky-800',
  delivered: 'bg-green-100 text-green-800',
}

export function ModelBadge({ status }: { status: ModelStatus }) {
  return <span className={`inline-block rounded px-1.5 py-px text-[11px] font-medium ${STYLE[status]}`}>{LABEL[status]}</span>
}

function Box({ title, extra, children }: { title: ReactNode; extra?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="ml-auto">{extra}</span>
      </div>
      {children}
    </section>
  )
}

/** 模型与交付：模型版本（候选 → 已验收 → 已交付）、升级门槛、产出运行、交付清单。 */
export default function ModelsPage() {
  const { name, version } = useParams()
  const scope = useScope()
  const id = scope.pid
  const models = useQuery({ queryKey: ['models', id], queryFn: () => api.models(id) })
  // 交付阶段与总览看全部模型；其他阶段只看本阶段步骤产出的版本
  const narrow = !!scope.stage && stageKind(scope.stage.id) !== 'delivery'
  const all = (models.data?.models ?? [])
    .map((m) => (narrow ? { ...m, versions: m.versions.filter((v) => inScope(scope, v.step)) } : m))
    .filter((m) => m.versions.length)
  const versions = all.flatMap((m) => m.versions)
  const latest = [...versions].sort((a, b) => b.registered_at.localeCompare(a.registered_at))[0]
  const selected = name && version ? { name, version } : latest ? { name: latest.name, version: latest.version } : null
  const count = (s: ModelStatus) => versions.filter((v) => v.status === s).length

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-4">
      {models.isLoading && <p className="text-sm text-slate-500">读取模型登记…</p>}
      {models.error && <p className="text-sm text-red-600">{(models.error as Error).message}</p>}
      {models.data && !versions.length && <Empty />}
      {versions.length > 0 && (
        <>
          <p className="mb-3 text-sm text-slate-700">
            共 {all.length} 个模型、{versions.length} 个版本：已交付 {count('delivered')}、已验收 {count('accepted')}、候选 {count('candidate')}。
            每个版本关联产出它的运行，训练数据版本、代码版本和指标都从运行记录追溯。
          </p>
          <div className="grid gap-4 lg:grid-cols-[19rem_1fr]">
            <ModelList base={scope.base} models={all} selected={selected} />
            {selected && <Detail key={`${selected.name}/${selected.version}`} pid={id} name={selected.name} version={selected.version} />}
          </div>
        </>
      )}
    </div>
  )
}

function Empty() {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 p-6 text-sm leading-relaxed text-slate-600">
      还没有登记模型。在训练脚本里用 SDK 登记，会自动关联本次运行（训练数据版本、代码版本、指标都能追溯）：
      <pre className="mt-2 overflow-x-auto rounded bg-slate-100 p-2 font-mono text-xs">
        {`with dsflow.start_run("7.1", hypothesis="…") as run:\n    run.log_input("…/features.parquet", name="features")\n    run.log_metrics({"MAE_验证": 3.2})\n    run.log_model("…/outputs/model.json", "sku_demand")\n    run.set_conclusion("…", validity="有效")`}
      </pre>
      也可以用命令行：<code className="rounded bg-slate-100 px-1">uv run dsflow model add 项目目录 模型文件 --name 模型名 --run 运行编号</code>
    </div>
  )
}

function firstMetric(v: ModelVersion): string {
  const m = Object.entries(v.run?.metrics ?? {})[0]
  return m ? `${m[0]} ${m[1] == null ? '—' : fmtNum(m[1], 4)}` : ''
}

function ModelList({ base, models, selected }: { base: string; models: ModelEntry[]; selected: { name: string; version: string } | null }) {
  return (
    <nav className="space-y-3" aria-label="模型版本">
      {models.map((m) => (
        <section key={m.name} className="rounded-lg border border-slate-200 bg-white p-2">
          <h2 className="px-1 text-sm font-semibold">{m.name}</h2>
          {m.description && <p className="px-1 text-xs text-slate-500">{m.description}</p>}
          <ul className="mt-1 space-y-0.5">
            {[...m.versions].reverse().map((v) => {
              const active = selected?.name === m.name && selected.version === v.version
              return (
                <li key={v.version}>
                  <Link
                    to={`${base}/models/${encodeURIComponent(m.name)}/${v.version}`}
                    className={`block rounded px-1.5 py-1 text-xs ${active ? 'bg-blue-50 ring-1 ring-blue-200' : 'hover:bg-slate-50'}`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono">{v.version}</span>
                      <ModelBadge status={v.status} />
                      <span className="ml-auto text-[11px] text-slate-500">{fmtTime(v.registered_at).slice(0, 10)}</span>
                    </div>
                    <div className="mt-0.5 text-[11px] text-slate-500">
                      {v.step ? `步骤 ${v.step}` : '没有关联运行'}
                      {firstMetric(v) && ` · ${firstMetric(v)}`}
                    </div>
                  </Link>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </nav>
  )
}

function Detail({ pid, name, version }: { pid: string; name: string; version: string }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['model', pid, name, version], queryFn: () => api.model(pid, name, version) })
  const [note, setNote] = useState('')
  const refresh = () => {
    for (const key of [['model', pid, name, version], ['models', pid], ['board', pid]]) qc.invalidateQueries({ queryKey: key })
  }
  const status = useMutation({
    mutationFn: (to: ModelStatus) => api.setModelStatus(pid, name, version, to, note),
    onSuccess: () => {
      setNote('')
      refresh()
    },
  })
  const draft = useMutation({ mutationFn: () => api.makeChecklist(pid, name, version), onSuccess: refresh })
  if (q.isLoading) return <p className="text-sm text-slate-500">读取中…</p>
  if (q.error) return <p className="text-sm text-red-600">{(q.error as Error).message}</p>
  const d = q.data!
  const blocking = d.gates.filter((g) => g.blocking && !g.passed)
  const back: ModelStatus | null = d.status === 'accepted' ? 'candidate' : d.status === 'delivered' ? 'accepted' : null
  const forward: ModelStatus | null = d.status === 'delivered' ? null : d.target
  const headline =
    d.status === 'delivered'
      ? d.checklist.complete
        ? '已交付，交付清单齐全。'
        : `已交付，但交付清单${d.checklist.summary}。`
      : blocking.length
        ? `还不能标为「${LABEL[d.target]}」：还差 ${blocking.length} 项（${blocking.map((g) => g.label).join('、')}）。`
        : `可以标为「${LABEL[d.target]}」：门槛都已满足，写明理由后即可变更。`

  return (
    <div className="min-w-0 space-y-3">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold">{d.name}</h2>
        <span className="font-mono text-sm">{d.version}</span>
        <ModelBadge status={d.status} />
        <span className="text-xs text-slate-500">
          {d.path} · {fmtBytes(d.size_bytes)} · 登记于 {fmtTime(d.registered_at)}
        </span>
      </header>

      <section className={`rounded-lg border p-3 ${d.status === 'delivered' && d.checklist.complete ? 'border-green-200 bg-green-50/60' : blocking.length ? 'border-amber-200 bg-amber-50/60' : 'border-blue-200 bg-blue-50/60'}`}>
        <p className="text-base font-semibold leading-relaxed">{headline}</p>
        {d.description && <p className="mt-1 text-sm text-slate-700">{d.description}</p>}
      </section>

      <Box title={d.status === 'delivered' ? '交付状态的核对' : `升到「${LABEL[d.target]}」的门槛`}>
        <Gates gates={d.gates} />
        <div className="mt-3 border-t border-slate-100 pt-2">
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="写明理由（记入历史），例如：验证期与最终评估期都低于最好的基线，已知例外已和业务确认"
            aria-label="状态变更理由"
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm outline-none focus:border-blue-500"
          />
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            {forward && (
              <button
                onClick={() => status.mutate(forward)}
                disabled={!!blocking.length || !note.trim() || status.isPending}
                title={blocking.length ? '门槛未满足' : !note.trim() ? '先写理由' : undefined}
                className="rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                标为「{LABEL[forward]}」
              </button>
            )}
            {back && (
              <button
                onClick={() => status.mutate(back)}
                disabled={!note.trim() || status.isPending}
                className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                退回「{LABEL[back]}」
              </button>
            )}
            {status.error && <span className="text-xs text-red-600">{(status.error as Error).message}</span>}
          </div>
        </div>
      </Box>

      <RunBox pid={pid} d={d} />
      <ChecklistBox report={d.checklist} readonly={d.readonly} onDraft={() => draft.mutate()} pending={draft.isPending} error={draft.error} />

      <Box title={`状态历史（${d.history.length}）`}>
        <ol className="space-y-1 text-sm">
          {[...d.history].reverse().map((h, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-2">
              <span className="tabular w-36 shrink-0 text-xs text-slate-500">{fmtTime(h.at)}</span>
              <ModelBadge status={h.status} />
              <span>{h.note}</span>
            </li>
          ))}
        </ol>
      </Box>
    </div>
  )
}

function Gates({ gates }: { gates: Gate[] }) {
  return (
    <ul className="space-y-1 text-sm">
      {gates.map((g) => (
        <li key={g.code} className="flex items-start gap-2">
          {g.passed ? (
            <span className="inline-flex w-16 shrink-0 items-center gap-0.5 text-xs text-green-800">
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
              满足
            </span>
          ) : g.blocking ? (
            <span className="inline-flex w-16 shrink-0 items-center gap-0.5 text-xs text-red-700">
              <XCircle className="h-3.5 w-3.5" aria-hidden />
              未满足
            </span>
          ) : (
            <span className="inline-flex w-16 shrink-0 items-center gap-0.5 text-xs text-amber-900">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
              提示
            </span>
          )}
          <span className="min-w-0">
            {g.label}
            <span className="ml-2 text-xs text-slate-500">{g.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

function RunBox({ pid, d }: { pid: string; d: ModelDetail }) {
  const r = d.run
  if (!r)
    return (
      <Box title="产出运行">
        <p className="text-sm text-amber-900">
          登记时没有关联运行：训练数据版本和指标无法追溯。在训练脚本里用 run.log_model 登记，或 dsflow model add … --run 运行编号。
        </p>
      </Box>
    )
  return (
    <Box
      title="产出运行"
      extra={
        <Link to={`/p/${pid}/runs/${r.run_id}`} className="font-mono text-xs text-blue-700 hover:underline">
          {r.run_id}
        </Link>
      }
    >
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <Link to={`/p/${pid}/steps/${r.step}`} className="text-blue-700 hover:underline">
          步骤 {r.step}
        </Link>
        <ValidityBadge validity={r.validity} />
        <span className="text-slate-700">{r.conclusion || r.hypothesis}</span>
      </p>
      <div className="mt-2 grid gap-3 text-xs sm:grid-cols-2">
        <div>
          <p className="mb-0.5 text-slate-500">指标</p>
          <table className="tabular">
            <tbody>
              {Object.entries(r.metrics).map(([k, val]) => (
                <tr key={k}>
                  <td className="pr-3 text-slate-600">{k}</td>
                  <td className="font-semibold">{val == null ? '—' : fmtNum(val, 6)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <p className="mb-0.5 text-slate-500">训练数据版本</p>
          <ul className="space-y-0.5">
            {r.inputs.map((x) => (
              <li key={`${x.name}-${x.version}`}>
                {x.name} <span className="font-mono text-[10px] text-slate-400">{x.version}</span>
                {x.rows != null && <span className="tabular ml-1 text-slate-500">{fmtInt(x.rows)} 行</span>}
              </li>
            ))}
            {!r.inputs.length && <li className="text-slate-400">没有登记</li>}
          </ul>
          <p className="mt-1.5 text-slate-500">
            代码版本：<span className="font-mono">{r.git_commit ? r.git_commit.slice(0, 10) : '不是 git 仓库'}</span>
            {r.git_dirty && <span className="text-amber-700">（有未提交改动）</span>}
          </p>
        </div>
      </div>
    </Box>
  )
}

function ChecklistBox({ report, readonly, onDraft, pending, error }: {
  report: ChecklistReport
  readonly: boolean
  onDraft: () => void
  pending: boolean
  error: unknown
}) {
  const failing = report.items.filter((i) => !i.passed)
  const button = !readonly && (
    <button
      onClick={onDraft}
      disabled={pending}
      className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-50"
      title="事实部分（版本、复现入口、训练数据版本、指标数值）按登记与运行记录重写；人写的部分保留"
    >
      {report.exists ? <RefreshCw className="h-3.5 w-3.5" aria-hidden /> : <FilePlus2 className="h-3.5 w-3.5" aria-hidden />}
      {pending ? '写入中…' : report.exists ? '刷新事实部分' : '生成交付清单草稿'}
    </button>
  )
  return (
    <Box title={report.exists && !report.error ? `交付清单 · ${report.passed}/${report.total} 项通过` : '交付清单'} extra={button}>
      <p className="mb-1 font-mono text-xs text-slate-500">{report.path}</p>
      {readonly && (
        <p className="mb-1 inline-flex items-center gap-1 text-xs text-slate-600">
          <Lock className="h-3 w-3" aria-hidden />
          只读接入：平台不写项目文件，交付清单要由执行 agent 在项目里写（或在项目环境里运行 dsflow delivery init）。
        </p>
      )}
      {error ? <p className="text-xs text-red-600">{(error as Error).message}</p> : null}
      {report.error && <p className="text-sm text-red-700">{report.error}</p>}
      {!report.exists && !readonly && (
        <p className="text-sm text-slate-600">
          还没有交付清单。先生成草稿：平台填好模型版本、复现入口、训练数据版本和指标数值，一句话说明、使用入口、适用边界、监控方案等标着「待填」，由执行 agent 或你补完。
        </p>
      )}
      {failing.length > 0 && (
        <ul className="mb-2 space-y-0.5 text-sm">
          {failing.map((i) => (
            <li key={i.label} className="flex items-start gap-1.5 text-red-800">
              <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              <span>
                {i.label}
                {i.detail && <span className="ml-1 text-xs text-slate-600">{i.detail}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {report.complete && (
        <p className="mb-2 inline-flex items-center gap-1 text-sm text-green-800">
          <CheckCircle2 className="h-4 w-4" aria-hidden />
          {report.total} 项全部通过：版本一致、数据版本与指标数值与产出运行一致、产物都在、没有「待填」。
        </p>
      )}
      {report.notes.length > 0 && <p className="mb-2 text-xs text-slate-600">另外：{report.notes.join('；')}。</p>}
      {report.checklist && <ChecklistView c={report.checklist} />}
    </Box>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </>
  )
}

function List({ items }: { items: string[] }) {
  if (!items.length) return <span className="text-slate-400">—</span>
  return (
    <ul className="list-disc pl-4">
      {items.map((x, i) => (
        <li key={i} className={x.includes('待填') ? 'text-amber-800' : ''}>
          {x}
        </li>
      ))}
    </ul>
  )
}

function ChecklistView({ c }: { c: DeliveryChecklist }) {
  const [copied, setCopied] = useState(false)
  const text = c.reproduce.join('\n')
  return (
    <details className="text-sm" open>
      <summary className="cursor-pointer text-xs text-slate-600">清单内容</summary>
      <dl className="mt-2 grid grid-cols-[6.5rem_1fr] gap-x-3 gap-y-2 leading-relaxed">
        <Row label="一句话说明">
          <span className={c.summary.includes('待填') ? 'text-amber-800' : 'font-medium'}>{c.summary || '—'}</span>
        </Row>
        <Row label="使用入口">
          <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-slate-50 p-1.5 font-mono text-xs">{c.usage.join('\n') || '—'}</pre>
        </Row>
        <Row label="适用范围">
          <List items={c.applicability.scope} />
        </Row>
        <Row label="不适用">
          <List items={c.applicability.not_for} />
        </Row>
        <Row label="训练数据期间">{c.applicability.data_period || '—'}</Row>
        {c.applicability.known_weaknesses.length > 0 && (
          <Row label="已知弱点">
            <List items={c.applicability.known_weaknesses} />
          </Row>
        )}
        <Row label="指标">
          <div className="overflow-x-auto">
            <table className="tabular text-xs">
              <thead className="text-left text-slate-500">
                <tr>
                  <th className="pr-3 font-normal">指标</th>
                  <th className="pr-3 text-right font-normal">数值</th>
                  <th className="pr-3 font-normal">对照</th>
                  <th className="font-normal">口径</th>
                </tr>
              </thead>
              <tbody>
                {c.metrics.map((m) => (
                  <tr key={m.name} className="border-t border-slate-100 align-top">
                    <td className="pr-3">{m.name}</td>
                    <td className="pr-3 text-right font-semibold">{m.value == null ? '—' : fmtNum(m.value, 4)}</td>
                    <td className="pr-3">{m.baseline || '—'}</td>
                    <td className={m.scope.includes('待填') ? 'text-amber-800' : ''}>{m.scope}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Row>
        <Row label="监控方案">
          <div className="overflow-x-auto">
            <table className="text-xs">
              <thead className="text-left text-slate-500">
                <tr>
                  <th className="pr-3 font-normal">看什么</th>
                  <th className="pr-3 font-normal">阈值</th>
                  <th className="pr-3 font-normal">频率</th>
                  <th className="font-normal">超过后做什么</th>
                </tr>
              </thead>
              <tbody>
                {c.monitoring.map((m, i) => (
                  <tr key={i} className="border-t border-slate-100 align-top">
                    <td className="pr-3">{m.metric}</td>
                    <td className="pr-3">{m.threshold}</td>
                    <td className="pr-3">{m.frequency}</td>
                    <td>{m.action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Row>
        <Row label="部署方式">{c.deployment}</Row>
        {c.open_items.length > 0 && (
          <Row label="遗留问题">
            <List items={c.open_items} />
          </Row>
        )}
        <Row label="训练数据">
          <ul className="text-xs">
            {c.data.map((x) => (
              <li key={`${x.name}-${x.version}`}>
                {x.name} <span className="font-mono text-slate-500">{x.version}</span> <span className="font-mono text-slate-400">{x.path}</span>
              </li>
            ))}
          </ul>
        </Row>
        <Row label="产物">
          <ul className="text-xs">
            {c.artifacts.map((a) => (
              <li key={a.path}>
                <span className="font-mono">{a.path}</span> <span className="text-slate-600">{a.purpose}</span>
              </li>
            ))}
          </ul>
        </Row>
        <Row label="复现入口">
          <div className="relative">
            <pre className="overflow-x-auto rounded bg-slate-900 p-2 font-mono text-[11px] leading-relaxed text-slate-100">{text || '—'}</pre>
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
        </Row>
      </dl>
    </details>
  )
}
