import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FolderPlus } from 'lucide-react'
import { api } from '../api'

/** 导入已有项目目录（需包含 lifecycle/steps.json）。默认只读：平台不在项目目录里写任何文件。 */
export default function ImportProjectForm({ onDone }: { onDone?: () => void }) {
  const [path, setPath] = useState('')
  const [writable, setWritable] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const mutation = useMutation({
    mutationFn: () => api.addProject(path.trim(), !writable),
    onSuccess: (row) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setPath('')
      onDone?.()
      navigate(`/p/${row.id}`)
    },
  })
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (path.trim()) mutation.mutate()
      }}
      className="space-y-2"
    >
      <label className="block text-xs text-slate-600">
        项目目录（包含 lifecycle/steps.json）
        <input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="D:\work\我的项目"
          autoFocus
          className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-sm outline-none focus:border-blue-500"
        />
      </label>
      <label className="flex items-center gap-1.5 text-xs text-slate-600">
        <input type="checkbox" checked={writable} onChange={(e) => setWritable(e.target.checked)} />
        允许平台写入（默认只读：运行记录、缓存都放在平台目录）
      </label>
      <button
        type="submit"
        disabled={mutation.isPending || !path.trim()}
        className="inline-flex items-center gap-1 rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        <FolderPlus className="h-4 w-4" aria-hidden />
        {mutation.isPending ? '导入中…' : '导入'}
      </button>
      {mutation.error && <p className="text-xs text-red-600">{(mutation.error as Error).message}</p>}
    </form>
  )
}
