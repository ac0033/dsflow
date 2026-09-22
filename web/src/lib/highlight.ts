import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import plaintext from 'highlight.js/lib/languages/plaintext'
import powershell from 'highlight.js/lib/languages/powershell'
import python from 'highlight.js/lib/languages/python'
import r from 'highlight.js/lib/languages/r'
import sql from 'highlight.js/lib/languages/sql'
import yaml from 'highlight.js/lib/languages/yaml'

const LANGS = { python, sql, json, yaml, bash, markdown, r, powershell, plaintext }
Object.entries(LANGS).forEach(([name, lang]) => hljs.registerLanguage(name, lang))
hljs.registerAliases(['py', 'pycon'], { languageName: 'python' })
hljs.registerAliases(['sh', 'shell', 'console'], { languageName: 'bash' })
hljs.registerAliases(['yml'], { languageName: 'yaml' })
hljs.registerAliases(['md', 'qmd'], { languageName: 'markdown' })
hljs.registerAliases(['ps1'], { languageName: 'powershell' })
hljs.registerAliases(['text', 'txt'], { languageName: 'plaintext' })

export const LANG_LABEL: Record<string, string> = {
  python: 'Python', py: 'Python', sql: 'SQL', json: 'JSON', yaml: 'YAML', yml: 'YAML', bash: 'Shell', sh: 'Shell',
  markdown: 'Markdown', r: 'R', powershell: 'PowerShell', ps1: 'PowerShell',
}

const BY_SUFFIX: Record<string, string> = {
  py: 'python', sql: 'sql', json: 'json', yaml: 'yaml', yml: 'yaml', sh: 'bash', md: 'markdown', qmd: 'markdown',
  r: 'r', ps1: 'powershell',
}

export function langForPath(path: string): string | undefined {
  return BY_SUFFIX[path.slice(path.lastIndexOf('.') + 1).toLowerCase()]
}

const escape = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** 返回高亮后的 HTML（highlight.js 输出已转义，可以直接插入）。超长代码不高亮，避免卡顿。 */
export function highlight(code: string, lang?: string): string {
  if (!lang || !hljs.getLanguage(lang) || code.length > 400_000) return escape(code)
  return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
}
