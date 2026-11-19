import { useEffect, useState } from 'react'
import { api } from '../../api'
import { pollWhileVisible } from '../../visible-poll'

export type RequestOutcome = 'success' | 'recovered' | 'blocked' | 'exhausted' | 'interrupted' | 'failed' | 'cancelled' | 'unknown'
export type RequestTotals = { requests: number; failed: number; recovered: number; uncertain: number; sameSource: number; crossSource: number }
export type GatewayRequest = {
  requestId: string; at: number; routeId: string; model: string; caller: string; outcome: RequestOutcome
  sourceId: string; upstreamModel?: string; status: number; error?: string; durationMs: number; attempts?: number
  switch?: 'source' | 'model'; blocks?: Record<string, number>; revision?: string
}
type RequestAttempt = { attempt: number; sourceId: string; model: string; status: number; success: boolean; at: number; error?: string }
export type RequestSnapshot = RequestTotals & { latest?: GatewayRequest; latestSwitch?: GatewayRequest }
export type RequestWindow = { from: number; to: number; end: number }
type RequestView = {
  now: number; totals: RequestTotals; routes: Record<string, string>; callers: Record<string, boolean>
  points: { from: number; to: number; totals: RequestTotals }[]
  outcomes: Partial<Record<RequestOutcome | 'uncertain', number>>
  recent: GatewayRequest[]
}
export type RequestDetail = { request: GatewayRequest; attempts: RequestAttempt[]; complete: boolean }

const base = '/agent/model-gateway/monitor'
export const loadRequestDetail = (id: string, signal: AbortSignal): Promise<{ data: RequestDetail }> =>
  api('GET', base + '/requests/' + encodeURIComponent(id), undefined, { signal })

export function useGatewayRequests(active: boolean, hours: number, route: string, caller: string, outcome: string, window: RequestWindow | null) {
  const [result, setResult] = useState<{ query: string; data?: RequestView; failed?: boolean; unsupported?: boolean } | null>(null)
  const [retry, setRetry] = useState(0)
  const params = new URLSearchParams({ view: 'requests', hours: String(hours) })
  if (route) params.set('routeId', route)
  if (caller) params.set('caller', caller)
  if (outcome) params.set('outcome', outcome)
  if (window) {
    params.set('from', String(window.from))
    params.set('to', String(window.to))
    params.set('end', String(window.end))
  }
  const query = params.toString()
  useEffect(() => {
    if (!active) return
    const poll = pollWhileVisible(async signal => {
      try {
        const { data } = await api('GET', base + '?' + query, undefined, { signal })
        if (!signal.aborted) setResult(Array.isArray(data?.recent) ? { query, data } : { query, unsupported: true })
      } catch (error) {
        if (!signal.aborted) setResult(previous => ({ query, data: previous?.query === query ? previous.data : undefined, failed: true }))
        throw error
      }
    }, 30_000)
    return poll.stop
  }, [active, query, retry])
  const pending = result?.query !== query
  return { data: result?.data, pending, failed: !pending && result?.failed, unsupported: !pending && result?.unsupported, retry: () => setRetry(value => value + 1) }
}
