import { useCallback, useEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { api } from '../../api'
import { agentCacheEpoch, agentDataKey, invalidateAgentData, peekAgentData, storeAgentData } from './agent-data-cache'
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
  const pending = useRef(false), sequence = useRef(0)
  const refresh = useCallback(() => { invalidateAgentData(agentDataKey(detailPath)); invalidateAgentData(agentDataKey(artifactPath)); const next = ++sequence.current; setVersion(next); return next }, [detailPath, artifactPath, scope])
  useEffect(() => {
    if (scope !== agentDataKey(detailPath)) return
    let cancelled = false
    const owner = agentCacheEpoch()
    if (stateScope !== scope) { setStateScope(scope); setDetail(seed<TaskDetail>(detailPath)); setControls(empty()); setArtifacts(seed<TaskArtifact[]>(artifactPath)) }
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 10000)
    pending.current = true
    async function read<T>(path: string, update: Dispatch<SetStateAction<Piece<T>>>) {
      const key = agentDataKey(path)
      try {
        const result = await api('GET', path, undefined, { signal: controller.signal })
        if (!cancelled) { if (!path.endsWith('/resources')) storeAgentData(key, result.data, owner); update({ value: result.data, version, failed: false }) }
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
  }, [id, version, scope])
  useEffect(() => { const timer = setInterval(() => { if (!pending.current && document.visibilityState === 'visible') refresh() }, 3000); return () => clearInterval(timer) }, [refresh])
  return { detail: stateScope === scope ? detail : seed<TaskDetail>(detailPath), controls: stateScope === scope ? controls : empty<TaskControls>(), artifacts: stateScope === scope ? artifacts : seed<TaskArtifact[]>(artifactPath), version, refresh }
}
