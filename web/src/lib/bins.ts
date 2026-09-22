import { fmtCompact, fmtNum } from './format'

/**
 * 把后端的等宽分箱（edges + counts）加上两端极端值格（under / over）转成图表用的格子。
 * 后端只在长尾明显时才裁剪范围，所以 under / over 为 0 时不显示两端格。
 */
export function binsFor(edges: number[], sets: { counts: number[]; under?: number; over?: number }[]) {
  const hasUnder = sets.some((s) => (s.under ?? 0) > 0)
  const hasOver = sets.some((s) => (s.over ?? 0) > 0)
  const lo = edges[0]
  const hi = edges[edges.length - 1]
  const labels: string[] = []
  const desc: string[] = []
  if (hasUnder) {
    labels.push(`<${fmtCompact(lo)}`)
    desc.push(`小于 ${fmtNum(lo)}（1% 分位以下的极端值）`)
  }
  sets[0].counts.forEach((_, i) => {
    labels.push(fmtCompact(edges[i]))
    desc.push(`${fmtNum(edges[i])} ~ ${fmtNum(edges[i + 1])}`)
  })
  if (hasOver) {
    labels.push(`>${fmtCompact(hi)}`)
    desc.push(`大于 ${fmtNum(hi)}（99% 分位以上的极端值）`)
  }
  const values = sets.map((s) => [...(hasUnder ? [s.under ?? 0] : []), ...s.counts, ...(hasOver ? [s.over ?? 0] : [])])
  const note = hasUnder || hasOver ? '取值有长尾：中间各格是 1%–99% 分位之间的等宽区间，两端各一格是更小 / 更大的极端值。' : ''
  return { labels, values, describe: (i: number) => desc[i], note }
}
