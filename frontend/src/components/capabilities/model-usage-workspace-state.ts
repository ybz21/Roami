import { useEffect, useState } from 'react'
import { api } from '../../api'
import { isAgentKind } from '../../agent-kind'
import { pollWhileVisible } from '../../visible-poll'
import type { GatewayCall, GatewayPrice, GatewayUsage } from '../settings/local-model-gateway'

export type UsageFilters = { days: number; start: string; end: string; sourceId: string; agentKind: string; model: string; source: string; state: string; search: string; page: number }
export type UsageWorkspaceData = GatewayUsage & { options: { sources: string[]; agents: string[]; models: string[] }; total: number; page: number; pageSize: number; archived: number; recent: (GatewayCall & { price?: GatewayPrice; finishedMs?: number })[] }
export const initialUsageFilters = (): UsageFilters => ({ days: 7, start: '', end: '', sourceId: '', agentKind: (() => { const kind = new URLSearchParams(location.hash.split('?')[1] || '').get('agentKind') || ''; return isAgentKind(kind) || ['external', 'roami'].includes(kind) ? kind : '' })(), model: '', source: '', state: '', search: '', page: 1 })
export function usageWorkspacePath(view: 'overview' | 'audit', filters: UsageFilters) {
  const q = new URLSearchParams({ view, days: String(filters.days < 0 ? 7 : filters.days) })
  for (const key of ['start', 'end', 'agentKind', 'model', 'source'] as const) if (filters[key]) q.set(key, filters[key])
  if (filters.sourceId === 'unknown') q.set('unattributed', '1')
  else if (filters.sourceId.startsWith('id:')) q.set('sourceId', filters.sourceId.slice(3))
  if (view === 'audit') {
    q.set('page', String(filters.page))
    if (filters.state) q.set('state', filters.state)
    if (filters.search.trim()) q.set('q', filters.search.trim())
  }
  return '/agent/model-gateway/usage?' + q
}
export function useUsageWorkspace(view: 'overview' | 'audit', filters: UsageFilters, version: number, paused: boolean) {
  const path = usageWorkspacePath(view, filters)
  const [result, setResult] = useState<{ path: string; data: UsageWorkspaceData } | null>(null)
  const [loading, setLoading] = useState(false), [failed, setFailed] = useState(false), [retry, setRetry] = useState(0)
  useEffect(() => {
    if (paused) return
    let alive = true
    const poll = pollWhileVisible(async signal => {
      setLoading(true)
      try {
        const { data } = await api('GET', path, undefined, { signal })
        if (alive && !signal.aborted) { setResult({ path, data }); setFailed(false) }
      } catch (error) { if (alive && !signal.aborted) setFailed(true); throw error }
      finally { if (alive && !signal.aborted) setLoading(false) }
    }, 30_000)
    return () => { alive = false; poll.stop() }
  }, [path, version, retry, paused])
  return { data: result?.path === path ? result.data : undefined, loading, failed, retry: () => setRetry(value => value + 1) }
}
