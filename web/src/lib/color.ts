export function hexA(hex: string, alpha: number): string {
  const v = hex.replace('#', '')
  const n = v.length === 3 ? v.split('').map((c) => c + c).join('') : v
  const r = parseInt(n.slice(0, 2), 16)
  const g = parseInt(n.slice(2, 4), 16)
  const b = parseInt(n.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}
