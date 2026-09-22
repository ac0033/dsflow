import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import type { Cell, DataColumn, TablePage } from '../types'

export const BLOCK = 200
const KEEP_BLOCKS = 80

/**
 * 按块（每块 200 行）向后端要数据：只取可视区附近的块，最多缓存 80 块（1.6 万行），
 * 远离当前位置的块会被丢弃，所以翻看几百万行也不会把浏览器内存吃满。
 */
export function useRowBlocks(fetchBlock: (offset: number, limit: number) => Promise<TablePage>, resetKey: string) {
  const blocks = useRef(new Map<number, Cell[][]>())
  const inflight = useRef(new Set<number>())
  const generation = useRef(0)
  const fetchRef = useRef(fetchBlock)
  fetchRef.current = fetchBlock
  const [, bump] = useReducer((x: number) => x + 1, 0)
  const [info, setInfo] = useState<{ columns: DataColumn[]; total: number } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback((b: number) => {
    if (b < 0 || blocks.current.has(b) || inflight.current.has(b)) return
    const gen = generation.current
    inflight.current.add(b)
    fetchRef
      .current(b * BLOCK, BLOCK)
      .then((page) => {
        if (gen !== generation.current) return
        blocks.current.set(b, page.rows)
        if (blocks.current.size > KEEP_BLOCKS) {
          const far = [...blocks.current.keys()].sort((x, y) => Math.abs(y - b) - Math.abs(x - b))
          far.slice(0, blocks.current.size - KEEP_BLOCKS).forEach((k) => blocks.current.delete(k))
        }
        setInfo({ columns: page.columns, total: page.total })
        bump()
      })
      .catch((e: Error) => gen === generation.current && setError(e.message))
      .finally(() => inflight.current.delete(b))
  }, [])

  useEffect(() => {
    // 不清空 info：换排序、筛选时表格保持挂载（横向位置不丢），新数据到来前行显示为占位条
    generation.current++
    blocks.current = new Map()
    inflight.current = new Set()
    setError(null)
    load(0)
    bump()
  }, [resetKey, load])

  const ensure = useCallback(
    (start: number, end: number) => {
      for (let b = Math.floor(start / BLOCK); b <= Math.floor(end / BLOCK); b++) load(b)
    },
    [load],
  )
  const getRow = (i: number) => blocks.current.get(Math.floor(i / BLOCK))?.[i % BLOCK]
  return { info, error, ensure, getRow }
}
