export function dirname(p: string): string {
  const i = p.lastIndexOf('/')
  return i < 0 ? '' : p.slice(0, i)
}

export function basename(p: string): string {
  return p.slice(p.lastIndexOf('/') + 1)
}

/**
 * 把报告里的链接解析成项目内的相对路径：相对链接按报告所在目录解析；
 * 指向项目目录的 Windows 绝对路径去掉项目根；外部链接、锚点、项目外的路径返回 null。
 */
export function resolvePath(baseDir: string, href: string, projectRoot?: string): string | null {
  if (!href || href.startsWith('#') || /^(https?|mailto|data|blob):/i.test(href)) return null
  let h = href.split('#')[0].split('?')[0]
  try {
    h = decodeURIComponent(h)
  } catch {
    /* 保留原样 */
  }
  h = h.replace(/\\/g, '/')
  if (!h) return null
  if (/^\/?[a-zA-Z]:\//.test(h)) {
    const abs = h.replace(/^\//, '')
    const root = projectRoot?.replace(/\\/g, '/').replace(/\/+$/, '')
    if (root && abs.toLowerCase().startsWith(root.toLowerCase() + '/')) return abs.slice(root.length + 1)
    return null
  }
  const parts = h.startsWith('/') ? [] : baseDir.split('/').filter(Boolean)
  for (const seg of h.split('/')) {
    if (seg === '..') {
      if (!parts.length) return null
      parts.pop()
    } else if (seg && seg !== '.') parts.push(seg)
  }
  return parts.join('/') || null
}

export const IMAGE_RE = /\.(png|jpe?g|gif|svg|webp)$/i
export const DATA_RE = /\.(csv|tsv|xlsx|parquet)$/i
