import { useCallback, useEffect, useState } from 'react'
import { agentDataKey, invalidateAgentData, loadAgentData, peekAgentData } from './agent-data-cache'

export function useAgentData<T>(path: string | null, freshFor: number, pollMs = 0, method = 'GET', enabled = true) {
  const key = path ? agentDataKey(path, method) : ''
  const [state, setState] = useState<{ key: string; value?: T; failed: boolean; errorCode?: string }>({ key: '', failed: false })
  const [revision, setRevision] = useState(0)
  const value = state.key === key ? state.value : key ? peekAgentData<T>(key) : undefined
  useEffect(() => {
    if (!path || !enabled) return
    let stopped = false, reading = false, failures = 0, ticks = 0
    const read = async (ttl: number) => {
      if (reading || agentDataKey(path, method) !== key) return
      reading = true
      try {
        const next = await loadAgentData<T>(path, ttl, method)
        failures = 0
        if (!stopped) setState({ key, value: next, failed: false })
      } catch (error: any) { failures = Math.min(failures + 1, 4); if (!stopped) setState(previous => ({ key, value: previous.key === key ? previous.value : peekAgentData<T>(key), failed: true, errorCode: typeof error?.apiError?.code === 'string' ? error.apiError.code : '' })) }
      finally { reading = false }
    }
    void read(freshFor)
    const timer = pollMs ? setInterval(() => {
      if (document.visibilityState !== 'visible' || reading || ++ticks < Math.min(2 ** failures, 10)) return
      ticks = 0; void read(0)
    }, pollMs) : undefined
    const foreground = () => { if (document.visibilityState === 'visible') void read(freshFor) }
    document.addEventListener('visibilitychange', foreground)
    return () => { stopped = true; clearInterval(timer); document.removeEventListener('visibilitychange', foreground) }
  }, [path, key, freshFor, pollMs, method, revision, enabled])
  const refresh = useCallback(() => { if (key) { invalidateAgentData(key); setRevision(value => value + 1) } }, [key])
  const failed = state.key === key && state.failed
  return { value, errorCode: state.key === key ? state.errorCode : undefined, loading: enabled && !!path && value === undefined && !failed, failed, refresh }
}
