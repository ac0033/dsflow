import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Loader2, Trash2, XCircle } from 'lucide-react'
import { api } from '../../api'

/*
 * 在网页上配答疑要用的模型：选一家 → 粘密钥 → 保存并连接，平台会真的发一句话过去测通。
 * 密钥只写进平台所在这台电脑的 models.json（这几个接口也只接受本机请求），和 `dsflow chat` 用同一份配置。
 */

export default function ModelSetup({ onDone }: { onDone?: () => void }) {
  const client = useQueryClient()
  const list = useQuery({ queryKey: ['askModels'], queryFn: api.askModels })
  const [preset, setPreset] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [more, setMore] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null)

  const presets = list.data?.presets ?? []
  const chosen = useMemo(() => presets.find((p) => p.preset === preset) ?? presets[0], [presets, preset])
  const refresh = () => {
    client.invalidateQueries({ queryKey: ['askModels'] })
    client.invalidateQueries({ queryKey: ['askStatus'] })
  }

  const save = useMutation({
    mutationFn: async () => {
      await api.addAskModel({ preset: chosen!.preset, api_key: apiKey, model, base_url: baseUrl })
      return api.testAskModel()
    },
    onSuccess: (got) => {
      setResult(got)
      setApiKey('')
      refresh()
    },
    onError: (e) => setResult({ ok: false, message: (e as Error).message }),
  })
  const pick = useMutation({
    mutationFn: (name: string) => api.useAskModel(name).then(() => api.testAskModel()),
    onSuccess: (got) => {
      setResult(got)
      refresh()
    },
    onError: (e) => setResult({ ok: false, message: (e as Error).message }),
  })
  const drop = useMutation({ mutationFn: (name: string) => api.deleteAskModel(name), onSuccess: refresh })

  if (list.error) return <p className="ask-err">{(list.error as Error).message}</p>
  if (!chosen) return <p className="ask-tool">读取可选的模型…</p>

  return (
    <section className="ask-setup">
      <h3>配置答疑要用的模型</h3>
      <p className="note">
        平台自己不带模型。选一家、把密钥粘进来就能用；密钥只写进这台电脑上的一个文件（
        <code title={list.data?.path}>models.json</code>），平台不会把它发到别处，也不会在页面上再显示出来。
      </p>

      <label>
        <span>选一家</span>
        <select value={chosen.preset} onChange={(e) => { setPreset(e.target.value); setResult(null) }}>
          {presets.map((p) => (
            <option key={p.preset} value={p.preset}>
              {p.label}
            </option>
          ))}
        </select>
      </label>
      {chosen.where && <p className="note">密钥在哪里申请：{chosen.where}</p>}

      {chosen.needs_key && (
        <label>
          <span>密钥</span>
          <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="粘贴 API 密钥" autoComplete="off" />
        </label>
      )}

      <button type="button" className="more" onClick={() => setMore(!more)}>
        {more ? '收起' : '换模型或自定义接口地址'}
      </button>
      {more && (
        <>
          <label>
            <span>模型 ID</span>
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder={chosen.model} />
          </label>
          <label>
            <span>接口地址</span>
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={chosen.base_url ?? '这家的官方地址'} />
          </label>
        </>
      )}

      <div className="row">
        <button type="button" className="go" onClick={() => { setResult(null); save.mutate() }} disabled={save.isPending || (chosen.needs_key && !apiKey.trim())}>
          {save.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
          保存并连接
        </button>
        {list.data?.models.length ? (
          <button type="button" onClick={() => { setResult(null); pick.mutate(list.data.models.find((m) => m.active)?.name ?? list.data.models[0].name) }} disabled={pick.isPending}>
            重新测一次
          </button>
        ) : null}
      </div>

      {result && (
        <p className={result.ok ? 'ok' : 'bad'}>
          {result.ok ? <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> : <XCircle className="h-3.5 w-3.5" aria-hidden />}
          <span className="min-w-0 flex-1">{result.ok ? `连上了，模型回了「${result.message}」。` : `没连上：${result.message}`}</span>
          {result.ok && (
            <button type="button" className="done" onClick={() => onDone?.()}>
              开始提问
            </button>
          )}
        </p>
      )}

      {(list.data?.models.length ?? 0) > 0 && (
        <ul className="saved">
          {list.data!.models.map((m) => (
            <li key={m.name}>
              <span className="min-w-0 flex-1 truncate" title={`${m.model}｜密钥 ${m.key}`}>
                {m.name}
                <span className="text-slate-400">｜{m.model}</span>
              </span>
              {m.active ? (
                <span className="tag">使用中</span>
              ) : (
                <button type="button" onClick={() => { setResult(null); pick.mutate(m.name) }}>
                  改用
                </button>
              )}
              <button type="button" onClick={() => drop.mutate(m.name)} aria-label={`删掉 ${m.name}`}>
                <Trash2 className="h-3 w-3" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
