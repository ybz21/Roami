import { useCallback, useEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { api } from '../../api'
import type { TaskArtifact, TaskControls, TaskDetail } from './agent-task-protocol'

type Piece<T> = { value: T | null; version: number; failed: boolean }
const empty = <T,>(): Piece<T> => ({ value: null, version: -1, failed: false })

export function useAgentTask(id: string) {
  const [version, setVersion] = useState(0)
  const [detail, setDetail] = useState(empty<TaskDetail>)
  const [controls, setControls] = useState(empty<TaskControls>)
  const [artifacts, setArtifacts] = useState(empty<TaskArtifact[]>)
  const pending = useRef(false), sequence = useRef(0)
  const refresh = useCallback(() => { const next = ++sequence.current; setVersion(next); return next }, [])
  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 10000)
    pending.current = true
    async function read<T>(path: string, update: Dispatch<SetStateAction<Piece<T>>>) {
      try {
        const result = await api('GET', path, undefined, { signal: controller.signal })
        if (!cancelled) update({ value: result.data, version, failed: false })
      } catch {
        if (!cancelled) update((previous) => ({ ...previous, version, failed: true }))
      }
    }
    void Promise.allSettled([
      read('/agent/tasks/' + encodeURIComponent(id), setDetail),
      read('/agent/tasks/' + encodeURIComponent(id) + '/resources', setControls),
      read('/agent/artifacts?taskId=' + encodeURIComponent(id), setArtifacts),
    ]).finally(() => { clearTimeout(timeout); if (!cancelled) pending.current = false })
    return () => { cancelled = true; clearTimeout(timeout); controller.abort(); pending.current = false }
  }, [id, version])
  useEffect(() => { const timer = setInterval(() => { if (!pending.current) refresh() }, 3000); return () => clearInterval(timer) }, [refresh])
  return { detail, controls, artifacts, version, refresh }
}
