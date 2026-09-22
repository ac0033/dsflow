import { createContext, useContext } from 'react'
import type { Stage } from '../types'

/** 当前视图的范围：总览（整个项目）或某个阶段。同一个页面在阶段里只显示本阶段步骤的内容。 */
export interface Scope {
  pid: string
  stage: Stage | null
  /** 本阶段的步骤编号；总览为 null（不过滤） */
  stepIds: Set<string> | null
  /** 本范围的路由前缀：/p/<id> 或 /p/<id>/stage/<阶段> */
  base: string
}

export const ScopeContext = createContext<Scope | null>(null)

export function useScope(): Scope {
  const scope = useContext(ScopeContext)
  if (!scope) throw new Error('useScope 只能在总览或阶段板块里使用')
  return scope
}

export const inScope = (scope: Scope, step?: string | null) => !scope.stepIds || (!!step && scope.stepIds.has(step))

export type StageKind = 'data' | 'model' | 'delivery'

/** 阶段性质决定板块里有哪些选项卡：①–⑤ 以数据为主，⑥–⑩ 以实验与模型为主，⑪ 是交付。 */
export const stageKind = (id: number): StageKind => (id <= 5 ? 'data' : id <= 10 ? 'model' : 'delivery')
