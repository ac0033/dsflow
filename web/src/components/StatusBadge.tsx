import type { StepStatus } from '../types'

const STYLE: Record<StepStatus, string> = {
  pending: 'bg-slate-100 text-slate-500',
  pending_approval: 'bg-orange-100 text-orange-700',
  in_progress: 'bg-yellow-100 text-yellow-800',
  awaiting_acceptance: 'bg-sky-100 text-sky-700',
  partial: 'bg-yellow-100 text-yellow-800',
  done: 'bg-green-100 text-green-700',
  stopped: 'bg-red-100 text-red-700',
}

export const STATUS_LABEL: Record<StepStatus, string> = {
  pending: '未开始',
  pending_approval: '待审批',
  in_progress: '进行中',
  awaiting_acceptance: '待验收',
  partial: '部分完成',
  done: '已完成',
  stopped: '已停止',
}

/** 状态圆点的颜色（旁边总有文字标签，不单靠颜色区分） */
export const STATUS_COLOR: Record<StepStatus, string> = {
  pending: '#94a3b8',
  pending_approval: '#f97316',
  in_progress: '#eab308',
  awaiting_acceptance: '#0ea5e9',
  partial: '#eab308',
  done: '#16a34a',
  stopped: '#dc2626',
}

export default function StatusBadge({ status }: { status: StepStatus }) {
  return (
    <span className={`inline-block rounded px-1.5 py-px text-[11px] font-medium ${STYLE[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  )
}
