import { useEffect, useState } from 'react'
import { api } from '../../api'
import { isAgentKind } from '../../agent-kind'
import { pollWhileVisible } from '../../visible-poll'
import type { GatewayCall, GatewayPrice, GatewayUsage } from '../settings/local-model-gateway'

export type UsageFilters = { day: string; hour: string; days: number; start: string; end: string; sourceId: string; agentKind: string; model: string; source: string; state: string; search: string; page: number }
export type UsageWorkspaceData = GatewayUsage & { accountingTimezone?: string; options: { sources: string[]; agents: string[]; models: string[] }; total: number; page: number; pageSize: number; archived: number; hourlyDay: string; nowMs?: number; recent: (GatewayCall & { price?: GatewayPrice; finishedMs?: number })[] }
export const initialUsageFilters = (): UsageFilters => {
  const params = new URLSearchParams(location.hash.split('?')[1] || '')
  const kind=params.get('agentKind') || '', value=(key:string)=>params.get(key) || ''
  const date=(key:string)=> { const text=value(key); return /^\d{4}-\d{2}-\d{2}$/.test(text) && Number.isFinite(Date.parse(text)) && new Date(text).toISOString().slice(0,10)===text ? text : '' }
  const days=Number(params.get('days') || 1)
  return {day:date('day'),hour:/^(?:[0-9]|1[0-9]|2[0-3])$/.test(value('hour')) ? value('hour') : '',days:[1,7,30,-1].includes(days)?days:1,start:date('start'),end:date('end'),sourceId:value('sourceId'),agentKind:isAgentKind(kind)||['external','roami'].includes(kind)?kind:'',model:value('model'),source:value('source'),state:value('state'),search:value('search'),page:1}
}
export function usageFilterQuery(filters: UsageFilters) {
  const params=new URLSearchParams({usageView:'audit',days:String(filters.days)})
  for(const key of ['start','end','day','hour','sourceId','agentKind','model','source','state','search'] as const) if(filters[key] !== '')params.set(key,filters[key])
  return params.toString()
}
export function usageWorkspacePath(view: 'overview' | 'audit', filters: UsageFilters) {
  const q = new URLSearchParams({ view, days: String(filters.days < 0 ? 7 : filters.days), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone })
  for (const key of ['start', 'end', 'day', 'agentKind', 'model', 'source'] as const) if (filters[key]) q.set(key, filters[key])
  if (filters.sourceId === 'unknown') q.set('unattributed', '1')
  else if (filters.sourceId.startsWith('id:')) q.set('sourceId', filters.sourceId.slice(3))
  if (view === 'audit') {
    q.set('page', String(filters.page))
    if (filters.hour !== '') q.set('hour', filters.hour)
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
