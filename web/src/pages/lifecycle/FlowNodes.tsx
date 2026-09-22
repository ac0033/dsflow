import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import { AlertTriangle, Database, RotateCcw } from 'lucide-react'
import StatusBadge from '../../components/StatusBadge'
import { hexA } from '../../lib/color'
import { fmtInt, fmtNum } from '../../lib/format'
import { basename } from '../../lib/paths'
import type { CardValue, LineageNode, Stage, StepNode } from '../../types'

export const NODE_W = 228

export type StepFlowData = { step: StepNode; stage: Stage; loops: number; visits?: number; dim: boolean }
export type LaneData = { stage: Stage; count: number; width: number; height: number }
export type LineageData = { item: LineageNode }

const val = (v: CardValue) => (v == null || v === '' ? '' : typeof v === 'number' ? fmtNum(v) : v)

/** 步骤节点：先给结论——有讲解用讲解开头，其次说明卡的一句话，再其次注册表里的结论。 */
function StepFlowNode({ data }: NodeProps<Node<StepFlowData, 'step'>>) {
  const { step, stage, loops, visits, dim } = data
  const card = step.card
  const pending = step.status === 'pending'
  return (
    <div
      className={`rounded-lg border bg-white shadow-sm transition-opacity ${pending ? 'border-dashed' : ''} ${step.issue_count ? 'ring-2 ring-red-500' : ''}`}
      style={{ width: NODE_W, opacity: dim ? 0.3 : pending ? 0.75 : 1, borderColor: step.status === 'pending_approval' ? stage.color : '#e2e8f0' }}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-slate-400" />
      <div className="flex items-center gap-1 rounded-t-lg px-2 py-1" style={{ background: hexA(stage.color, 0.14) }}>
        <span className="truncate text-[12px] font-bold" style={{ color: stage.color }} title={`${step.id} · ${step.title}`}>
          {step.id} · {step.title}
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-1">
          <StatusBadge status={step.status} />
          {step.current_revision && <span className="rounded bg-white/70 px-1 text-[10px] text-slate-600">↻{step.current_revision}</span>}
        </span>
      </div>
      <div className="space-y-1 px-2 py-1.5 text-[11.5px] leading-snug">
        {step.brief ? (
          // 有讲解就用讲解开头（讲给人听的话）：目的一句、结论一句；数字在讲解里有出处，节点上不摆
          <>
            <p className="line-clamp-2 text-slate-600">
              <span className="mr-1 rounded bg-slate-100 px-1 text-[10px] font-bold text-slate-600">目的</span>
              {step.brief.question}
            </p>
            <p className="line-clamp-3 font-medium text-slate-800">
              <span className={`mr-1 rounded px-1 text-[10px] font-bold ${step.brief.can_continue === false ? 'bg-amber-100 text-amber-800' : 'bg-blue-100 text-blue-700'}`}>
                {step.brief.can_continue === false ? '暂不能继续' : '结论'}
              </span>
              {step.brief.answer}
            </p>
          </>
        ) : card ? (
          <>
            <p className="line-clamp-3 font-medium text-slate-800">{card.headline}</p>
            {card.numbers.map((n, i) => (
              <p key={i} className="tabular truncate text-slate-600" title={n.scope}>
                {n.label}：{val(n.before) && `${val(n.before)} → `}
                <b className="text-slate-800">{val(n.after) || val(n.change)}</b> {n.unit}
              </p>
            ))}
            {card.artifacts.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {card.artifacts.map((a) => (
                  <span key={a} className="max-w-[100px] truncate rounded bg-slate-100 px-1 text-[10px] text-slate-600" title={a}>
                    {basename(a)}
                  </span>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            {step.finding ? (
              <p className="line-clamp-3 text-slate-800">
                <span className="mr-1 rounded bg-blue-100 px-1 text-[10px] font-bold text-blue-700">结论</span>
                {step.finding}
              </p>
            ) : (
              <p className="line-clamp-2 text-slate-600">
                <span className="mr-1 rounded bg-slate-100 px-1 text-[10px] font-bold text-slate-600">目的</span>
                {step.op}
              </p>
            )}
            {step.decision && (
              <p className="line-clamp-2 text-slate-600">
                <span className="mr-1 rounded bg-amber-100 px-1 text-[10px] font-bold text-amber-700">决策</span>
                {step.decision}
              </p>
            )}
          </>
        )}
        {(loops > 0 || step.issue_count > 0 || (visits ?? 0) > 1) && (
          <div className="flex flex-wrap gap-2 pt-0.5 text-[10.5px]">
            {loops > 0 && (
              <span className="inline-flex items-center gap-0.5 text-red-700">
                <RotateCcw className="h-3 w-3" aria-hidden />
                返工 {loops} 次
              </span>
            )}
            {step.issue_count > 0 && (
              <span className="inline-flex items-center gap-0.5 text-red-700">
                <AlertTriangle className="h-3 w-3" aria-hidden />
                {step.issue_count} 个校验问题
              </span>
            )}
            {(visits ?? 0) > 1 && <span className="text-slate-500">推进 {visits} 轮</span>}
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-slate-400" />
    </div>
  )
}

function LaneNode({ data }: NodeProps<Node<LaneData, 'lane'>>) {
  const { stage, count, width, height } = data
  return (
    <div style={{ width, height, background: hexA(stage.color, count ? 0.05 : 0.025), borderTop: '1px solid #e2e8f0' }}>
      <div className="flex h-full w-[150px] flex-col justify-center border-r border-slate-200 px-3" style={{ borderLeft: `4px solid ${stage.color}` }}>
        <span className="text-[12px] font-semibold text-slate-700">{stage.name}</span>
        <span className="text-[10.5px] text-slate-500">{count ? `${count} 个目的步骤` : '尚无步骤'}</span>
      </div>
    </div>
  )
}

function DatasetNode({ data }: NodeProps<Node<LineageData, 'dataset'>>) {
  const d = data.item
  return (
    <div className={`w-[210px] rounded-xl border bg-white px-2.5 py-1.5 shadow-sm ${d.missing ? 'border-dashed border-amber-400' : 'border-blue-200'}`}>
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-slate-400" />
      <div className="flex items-center gap-1 text-[12px] font-semibold">
        <Database className="h-3.5 w-3.5 shrink-0 text-blue-600" aria-hidden />
        <span className="truncate">{d.name}</span>
        {d.version && <span className="ml-auto shrink-0 font-mono text-[9.5px] text-slate-400">{d.version}</span>}
      </div>
      <p className="tabular text-[11px] text-slate-600">
        {d.missing ? '被引用但未登记' : d.rows != null ? `${fmtInt(d.rows)} 行 × ${d.columns} 列` : '尚未转换'}
        {d.stage_label && <span className="ml-1 text-slate-400">· {d.stage_label}</span>}
      </p>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-slate-400" />
    </div>
  )
}

function StepChipNode({ data }: NodeProps<Node<LineageData, 'stepchip'>>) {
  return (
    <div className="w-[110px] rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-center text-[12px] font-semibold text-amber-900">
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-slate-400" />
      步骤 {data.item.step}
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-slate-400" />
    </div>
  )
}

export const nodeTypes = { step: StepFlowNode, lane: LaneNode, dataset: DatasetNode, stepchip: StepChipNode }
