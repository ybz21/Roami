import { useEffect, useState } from 'react'
import { api } from '../../api'

export type AgentContext = { estimatedTokens: number; contextWindow?: number | null; compactionThreshold?: number | null; compactionRatio?: number; model?: string; snapshotId?: string }

export function useAgentContext(cid: string, node: string | null, model: string, revision: string, active: boolean) {
  const scope = JSON.stringify([node, cid, model])
  const [state, setState] = useState<{ scope: string; data: AgentContext | null; failed: boolean }>({ scope, data: null, failed: false })
  useEffect(() => {
    if (!cid) return
    const abort = new AbortController()
    let pending = false
    const refresh = async () => {
      if (pending || document.visibilityState === 'hidden') return
      pending = true
      try {
        const { data } = await api('GET', `/agent/conversations/${encodeURIComponent(cid)}/context`, undefined, { signal: abort.signal })
        if (!Number.isFinite(data?.estimatedTokens) || data.estimatedTokens < 0) throw Error('INVALID_CONTEXT_USAGE')
        if (!abort.signal.aborted) setState({ scope, data, failed: false })
      } catch {
        if (!abort.signal.aborted) setState(previous => ({ scope, data: previous.scope === scope ? previous.data : null, failed: true }))
      } finally { pending = false }
    }
    void refresh()
    const timer = active ? setInterval(() => { void refresh() }, 5000) : undefined
    document.addEventListener('visibilitychange', refresh)
    return () => { abort.abort(); clearInterval(timer); document.removeEventListener('visibilitychange', refresh) }
  }, [cid, scope, revision, active])
  return state.scope === scope ? state : { scope, data: null, failed: false }
}
