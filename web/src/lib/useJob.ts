import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Job } from '../types'

/** 跟踪一个后台任务：每 0.5 秒轮询一次，完成后回调。 */
export function useJob<T>(onDone?: (result: T) => void) {
  const [job, setJob] = useState<Job<T> | null>(null)
  const done = useRef(onDone)
  done.current = onDone

  useEffect(() => {
    if (!job || job.status === 'succeeded' || job.status === 'failed') return
    const timer = setTimeout(async () => {
      try {
        setJob(await api.job<T>(job.id))
      } catch (e) {
        setJob({ ...job, status: 'failed', error: (e as Error).message })
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [job])

  useEffect(() => {
    if (job?.status === 'succeeded') done.current?.(job.result as T)
  }, [job?.status, job?.result])

  return {
    job,
    running: job?.status === 'queued' || job?.status === 'running',
    start: (j: Job<unknown>) => setJob(j as Job<T>),
    reset: () => setJob(null),
  }
}
