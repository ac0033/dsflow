import { useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node, type ReactFlowInstance } from '@xyflow/react'
import dagre from '@dagrejs/dagre'
import '@xyflow/react/dist/style.css'
import { AlertTriangle } from 'lucide-react'
import { api } from '../../api'
import StatusBadge from '../../components/StatusBadge'
import type { Graph, Lineage, PathEntry } from '../../types'
import { NODE_W, nodeTypes, type LaneData, type LineageData, type StepFlowData } from './FlowNodes'

// 节点之间留足空间，让连线上的依赖说明（如"字段含义与质量问题清单"）不被节点挡住
const COL = NODE_W + 96
const LABEL_W = 176
const ROW_FULL = 214
const ROW_EMPTY = 50
type View = 'deps' | 'path' | 'lineage'

const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: 'deps', label: '依赖视图', hint: '纵轴是 11 个阶段，横轴是执行顺序。灰色箭头是登记的依赖，红色虚线是回退到更早的步骤；节点下方写着返工次数。点击节点进入步骤工作区。' },
  { id: 'path', label: '实际推进路径', hint: '按日期把每一轮串起来：蓝色箭头是往后推进，红色虚线是跳回更早的步骤。箭头上的编号是第几次跳转和日期；同一步骤连续的轮次算作返工。下方表格列出每一站。' },
  { id: 'lineage', label: '数据血缘', hint: '已登记的数据集（蓝框）经由哪一步（黄框）变成下一个数据集。点击数据集打开数据视图，点击步骤进入步骤工作区。' },
]

const arrow = (color: string) => ({ type: MarkerType.ArrowClosed, color, width: 16, height: 16 })
const labelProps = (color: string) => ({
  labelStyle: { fontSize: 10, fill: color },
  labelBgStyle: { fill: '#f8fafc' },
  labelBgPadding: [4, 2] as [number, number],
})

function laneNodes(graph: Graph, visits: Map<string, number>, dimmed: (id: string) => boolean): Node[] {
  const nodes: Node[] = []
  const width = LABEL_W + Math.max(1, graph.nodes.length) * COL + 24
  let y = 0
  for (const stage of graph.stages) {
    const steps = graph.nodes.filter((n) => n.stage === stage.id)
    const height = steps.length ? ROW_FULL : ROW_EMPTY
    nodes.push({
      id: `lane-${stage.id}`, type: 'lane', position: { x: 0, y }, draggable: false, selectable: false, focusable: false,
      zIndex: -1, style: { pointerEvents: 'none' }, data: { stage, count: steps.length, width, height } satisfies LaneData,
    })
    for (const step of steps) {
      nodes.push({
        id: step.id, type: 'step', position: { x: LABEL_W + (step.order - 1) * COL, y: y + 14 }, draggable: false,
        data: {
          step, stage, visits: visits.get(step.id), dim: dimmed(step.id),
          loops: graph.edges.filter((e) => e.type === 'revision_loop' && e.from === step.id).length,
        } satisfies StepFlowData,
      })
    }
    y += height
  }
  return nodes
}

function depEdges(graph: Graph, hovered: string | null): Edge[] {
  return graph.edges
    .filter((e) => e.type !== 'revision_loop')
    .map((e, i) => {
      const back = e.type === 'back'
      const color = back ? '#dc2626' : '#94a3b8'
      const active = !hovered || e.from === hovered || e.to === hovered
      return {
        id: `d${i}`, source: e.from, target: e.to, label: e.label || undefined, markerEnd: arrow(color),
        style: { stroke: color, strokeWidth: back ? 2 : 1.6, strokeDasharray: back ? '6 4' : undefined, opacity: active ? 1 : 0.12 },
        ...labelProps(back ? '#b91c1c' : '#64748b'),
      }
    })
}

function pathEdges(all: PathEntry[], hovered: string | null): Edge[] {
  // 有运行记录的步骤，以运行时间为准；它那些只能从文件修改时间推断日期的轮次不参与连线（表格里照常列出并注明"推断"）
  const withRuns = new Set(all.filter((p) => p.kind === 'run').map((p) => p.step))
  const path = all.filter((p) => p.kind === 'run' || !withRuns.has(p.step) || !p.date_source?.includes('推断'))
  const edges: Edge[] = []
  let k = 0
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1]
    const b = path[i]
    if (a.step === b.step) continue
    k++
    const back = b.order < a.order
    const color = back ? '#dc2626' : '#2a78d6'
    const active = !hovered || a.step === hovered || b.step === hovered
    edges.push({
      id: `p${i}`, source: a.step, target: b.step, label: `${k} · ${b.date ? b.date.slice(5, 10) : '日期未知'}`, markerEnd: arrow(color),
      style: { stroke: color, strokeWidth: 1.8, strokeDasharray: back ? '6 4' : undefined, opacity: active ? 1 : 0.12 },
      ...labelProps(back ? '#b91c1c' : '#1d4ed8'),
    })
  }
  return edges
}

function lineageLayout(lin: Lineage): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 28, ranksep: 80 })
  g.setDefaultEdgeLabel(() => ({}))
  const size = (type: string) => (type === 'dataset' ? { width: 210, height: 60 } : { width: 110, height: 34 })
  lin.nodes.forEach((n) => g.setNode(n.id, size(n.type)))
  lin.edges.forEach((e) => g.setEdge(e.from, e.to))
  dagre.layout(g)
  return {
    nodes: lin.nodes.map((n) => {
      const p = g.node(n.id)
      const s = size(n.type)
      return {
        id: n.id, type: n.type === 'dataset' ? 'dataset' : 'stepchip', draggable: false,
        position: { x: p.x - s.width / 2, y: p.y - s.height / 2 }, data: { item: n } satisfies LineageData,
      }
    }),
    edges: lin.edges.map((e, i) => ({ id: `l${i}`, source: e.from, target: e.to, markerEnd: arrow('#94a3b8'), style: { stroke: '#94a3b8', strokeWidth: 1.6 } })),
  }
}

export default function LifecyclePage() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const view = (params.get('view') as View) || 'deps'
  const [hovered, setHovered] = useState<string | null>(null)
  const project = useQuery({ queryKey: ['project', id], queryFn: () => api.project(id) })
  const lineage = useQuery({ queryKey: ['lineage', id], queryFn: () => api.lineage(id), enabled: view === 'lineage' })
  const graph = project.data?.graph

  const flow = useMemo(() => {
    if (view === 'lineage') return lineage.data ? lineageLayout(lineage.data) : { nodes: [], edges: [] }
    if (!graph) return { nodes: [], edges: [] }
    const edges = view === 'path' ? pathEdges(graph.path, hovered) : depEdges(graph, hovered)
    const near = new Set<string>(hovered ? [hovered] : [])
    edges.forEach((e) => {
      if (e.source === hovered) near.add(e.target)
      if (e.target === hovered) near.add(e.source)
    })
    const visits = new Map<string, number>()
    if (view === 'path') graph.path.forEach((p) => visits.set(p.step, (visits.get(p.step) ?? 0) + 1))
    return { nodes: laneNodes(graph, visits, (sid) => !!hovered && !near.has(sid)), edges }
  }, [view, graph, hovered, lineage.data])

  // 初始视野从左上角开始，缩放取 0.8–1（按内容宽度），保证节点里的字看得清；
  // 更宽的部分拖动查看，想看全貌点左下角"适应视图"。数据血缘仍整体适配。
  const boxRef = useRef<HTMLDivElement>(null)
  const laneWidth = graph ? LABEL_W + Math.max(1, graph.nodes.length) * COL + 24 : 1
  const initViewport = (inst: ReactFlowInstance) => {
    if (view === 'lineage') return
    const w = boxRef.current?.clientWidth ?? 1200
    inst.setViewport({ x: 8, y: 8, zoom: Math.max(0.8, Math.min(1, (w - 16) / laneWidth)) })
  }
  const errors = project.data?.issues.filter((i) => i.severity === 'error') ?? []
  const hint = VIEWS.find((v) => v.id === view)!.hint

  return (
    <div className="flex h-full flex-col px-6 pb-3 pt-3">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-md border border-slate-200 bg-white p-0.5" role="tablist">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              role="tab"
              aria-selected={view === v.id}
              onClick={() => setParams({ view: v.id })}
              className={`rounded px-3 py-1 text-sm ${view === v.id ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
            >
              {v.label}
            </button>
          ))}
        </div>
        <p className="min-w-0 flex-1 text-[12px] text-slate-500">{hint}</p>
      </div>
      {errors.length > 0 && (
        <div className="mb-2 flex items-start gap-1.5 rounded border border-red-200 bg-red-50 px-3 py-1.5 text-xs text-red-800">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          这个项目有 {errors.length} 个校验问题，图中标红的节点受影响：{errors.slice(0, 3).map((e) => e.message).join('；')}
          {errors.length > 3 ? ' …' : ''}
        </div>
      )}
      <div ref={boxRef} className="min-h-[420px] flex-1 overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
        {view === 'lineage' && lineage.data && !lineage.data.nodes.length ? (
          <p className="p-6 text-sm text-slate-500">
            还没有登记数据集。在<Link to={`/p/${id}/data?tab=chain`} className="text-blue-700 underline">数据 · 演变链与登记</Link>里登记，写上上游与产出步骤后，这里会画出数据如何经由各步骤演变。
          </p>
        ) : (
          <ReactFlow
            nodes={flow.nodes}
            edges={flow.edges}
            nodeTypes={nodeTypes}
            key={view}
            fitView={view === 'lineage'}
            fitViewOptions={{ padding: 0.1, maxZoom: 1 }}
            onInit={initViewport}
            minZoom={0.15}
            maxZoom={1.6}
            nodesConnectable={false}
            elementsSelectable={false}
            onNodeMouseEnter={(_, n) => (n.type === 'step' ? setHovered(n.id) : undefined)}
            onNodeMouseLeave={() => setHovered(null)}
            onNodeClick={(_, n) => {
              if (n.type === 'step') navigate(`/p/${id}/steps/${n.id}`)
              const item = (n.data as Partial<LineageData>).item
              if (n.type === 'stepchip' && item?.step) navigate(`/p/${id}/steps/${item.step}`)
              if (n.type === 'dataset' && item?.path) navigate(`/p/${id}/data?tab=files&path=${encodeURIComponent(item.path)}`)
            }}
          >
            <Background gap={24} color="#e2e8f0" />
            <Controls showInteractive={false} />
          </ReactFlow>
        )}
      </div>
      {view === 'path' && graph && <PathTable pid={id} path={graph.path} />}
    </div>
  )
}

function PathTable({ pid, path }: { pid: string; path: PathEntry[] }) {
  return (
    <details className="mt-2 rounded-lg border border-slate-200 bg-white text-xs" open>
      <summary className="cursor-pointer px-3 py-1.5 font-medium">推进时间线（{path.length} 站，按日期排列）</summary>
      <div className="max-h-56 overflow-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-slate-50 text-left text-[11px] text-slate-500">
            <tr>
              <th className="px-3 py-1 font-normal">日期</th>
              <th className="px-2 py-1 font-normal">步骤 · 轮次</th>
              <th className="px-2 py-1 font-normal">状态</th>
              <th className="px-2 py-1 font-normal">本轮摘要</th>
            </tr>
          </thead>
          <tbody>
            {path.map((p, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="tabular whitespace-nowrap px-3 py-1" title={p.date_source ? `日期来源：${p.date_source}` : undefined}>
                  {p.date ? p.date.replace('T', ' ').slice(0, 16) : '未知'}
                  {p.date_source?.includes('推断') && <span className="ml-1 text-slate-400">(推断)</span>}
                </td>
                <td className="whitespace-nowrap px-2 py-1">
                  {p.kind === 'run' ? (
                    <Link to={`/p/${pid}/runs/${p.run_id}`} className="text-blue-700 hover:underline">
                      <span className="mr-1 rounded bg-slate-100 px-1 text-[10px] text-slate-600">运行</span>
                      {p.step} · {p.title}
                      {p.validity ? ` · ${p.validity}` : ''}
                    </Link>
                  ) : (
                    <Link to={`/p/${pid}/steps/${p.step}?rev=${p.revision}`} className="text-blue-700 hover:underline">
                      <span className="mr-1 rounded bg-blue-50 px-1 text-[10px] text-blue-700">轮次</span>
                      {p.step} · {p.title} · {p.revision}
                    </Link>
                  )}
                </td>
                <td className="px-2 py-1">
                  <StatusBadge status={p.status} />
                </td>
                <td className="px-2 py-1 text-slate-600">{p.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}
