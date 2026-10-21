import { useCallback, useEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { agentDataKey, invalidateAgentData, peekAgentData, loadAgentData } from './agent-data-cache'
import { subscribeTaskChanges } from './agent-task-events'
import type { TaskArtifact, TaskControls, TaskDetail } from './agent-task-protocol'

type Piece<T> = { value: T | null; version: number; failed: boolean }
const empty = <T,>(): Piece<T> => ({ value: null, version: -1, failed: false })

export function useAgentTask(id: string) {
  const detailPath = '/agent/tasks/' + encodeURIComponent(id)
  const artifactPath = '/agent/artifacts?taskId=' + encodeURIComponent(id)
  const scope = agentDataKey(detailPath)
  const seed = <T,>(path: string): Piece<T> => ({ ...empty<T>(), value: peekAgentData<T>(agentDataKey(path)) || null })
  const [stateScope, setStateScope] = useState(scope)
  const [version, setVersion] = useState(0)
  const [detail, setDetail] = useState(() => seed<TaskDetail>(detailPath))
  const [controls, setControls] = useState(empty<TaskControls>)
  const [artifacts, setArtifacts] = useState(() => seed<TaskArtifact[]>(artifactPath))
  const pending = useRef(false), sequence = useRef(0), failures = useRef(0), ticks = useRef(0), queued = useRef(false)
  const reread = useCallback(() => { if (pending.current) { queued.current = true; return }; setVersion(++sequence.current) }, [scope])
  const refresh = useCallback(() => { invalidateAgentData(agentDataKey(detailPath)); invalidateAgentData(agentDataKey(artifactPath)); invalidateAgentData(agentDataKey(detailPath + '/resources')); const next = ++sequence.current; setVersion(next); return next }, [detailPath, artifactPath, scope])
  useEffect(() => {
    if (scope !== agentDataKey(detailPath)) return
    let cancelled = false
    if (stateScope !== scope) { setStateScope(scope); setDetail(seed<TaskDetail>(detailPath)); setControls(empty()); setArtifacts(seed<TaskArtifact[]>(artifactPath)) }
    let failed = false
    ticks.current = 0
    queued.current = false
    pending.current = true
    async function read<T>(path: string, update: Dispatch<SetStateAction<Piece<T>>>) {
      const key = agentDataKey(path)
      try {
        const value = await loadAgentData<T>(path)
        if (!cancelled && key === agentDataKey(path)) update({ value, version, failed: false })
      } catch {
        failed = true
        if (!cancelled) update((previous) => ({ ...previous, version, failed: true }))
      }
    }
    void Promise.allSettled([
      read('/agent/tasks/' + encodeURIComponent(id), setDetail),
      read('/agent/tasks/' + encodeURIComponent(id) + '/resources', setControls),
      read('/agent/artifacts?taskId=' + encodeURIComponent(id), setArtifacts),
    ]).finally(() => {
      if (cancelled) return
      pending.current = false
      failures.current = failed ? Math.min(failures.current + 1, 4) : 0
      if (queued.current) { queued.current = false; reread() }
    })
    return () => { cancelled = true; pending.current = false }
  }, [id, version, scope])
  const ended = stateScope === scope && !!detail.value && ['succeeded', 'failed', 'cancelled', 'interrupted'].includes(detail.value.task.state)
  useEffect(() => {
    if (ended) return
    const timer = setInterval(() => {
      if (pending.current || document.visibilityState !== 'visible') return
      if (++ticks.current < Math.min(2 ** failures.current, 10)) return
      ticks.current = 0; reread()
    }, 3000)
    return () => clearInterval(timer)
  }, [reread, ended])
  useEffect(() => {
    const changed = () => { if (document.visibilityState === 'visible') reread() }
    const unsubscribe = subscribeTaskChanges(id, changed)
    document.addEventListener('visibilitychange', changed)
    return () => { unsubscribe(); document.removeEventListener('visibilitychange', changed) }
  }, [id, scope, reread])
  return { detail: stateScope === scope ? detail : seed<TaskDetail>(detailPath), controls: stateScope === scope ? controls : empty<TaskControls>(), artifacts: stateScope === scope ? artifacts : seed<TaskArtifact[]>(artifactPath), version, refresh }
}
