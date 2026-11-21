import { useEffect, useState } from 'react'
import { api } from '../../api'
import { pollWhileVisible } from '../../visible-poll'

export type RequestOutcome = 'success' | 'recovered' | 'blocked' | 'exhausted' | 'interrupted' | 'failed' | 'cancelled' | 'unknown'
export const requestFailureReasons = ['blocked', 'exhausted', 'interrupted', 'upstreamLimited', 'upstreamUnauthorized', 'upstreamTimeout', 'connectFailed', 'dailyLimit', 'quota', 'failed'] as const
export type RequestFailureReason = typeof requestFailureReasons[number]
export type RequestSwitchFilter = '' | 'any' | 'failed'
export type RequestTotals = { requests: number; failed: number; recovered: number; uncertain: number; sameSource: number; crossSource: number; switchedFailed?: number }
export type GatewayRequest = {
  requestId: string; at: number; routeId: string; model: string; caller: string; outcome: RequestOutcome
  sourceId: string; upstreamModel?: string; status: number; error?: string; durationMs: number; attempts?: number
  switch?: 'source' | 'model'; blocks?: Record<string, number>; revision?: string
}
type RequestAttemptBilling = {
  state: 'settled' | 'pending' | 'unknown' | 'unrecorded' | 'missing' | 'unavailable'
  currency?: string; cost?: string; upstreamRequestId?: string
}
export type RequestAttempt = {
  attempt: number; sourceId: string; model: string; status: number; success: boolean; at: number; error?: string
  durationMs?: number; firstTokenMs?: number | null; groupPath?: string[]
  billing?: RequestAttemptBilling
}
export type RequestSnapshot = RequestTotals & { latest?: GatewayRequest; latestSwitch?: GatewayRequest }
export type RequestWindow = { from: number; to: number; end: number }
export type RequestLatency = { samples: number; p50: number; p95: number; p99: number }
export type RequestGroup = { id: string; totals: RequestTotals }
type RequestView = {
  now: number; totals: RequestTotals; routes: Record<string, string>; callers: Record<string, boolean>
  points: { from: number; to: number; totals: RequestTotals }[]
  outcomes: Partial<Record<RequestOutcome | 'uncertain', number>>
  failureReasons?: Partial<Record<RequestFailureReason, number>>
}
type RequestList = RequestView & { recent: GatewayRequest[] }
export type RequestSummary = RequestView & {
  range: { from: number; to: number }
  firstToken: RequestLatency | null; duration: RequestLatency | null
  tokens: { samples: number; input: number; output: number }
  byModel: RequestGroup[]; bySource: RequestGroup[]
}
export type RequestDetail = { request: GatewayRequest; attempts: RequestAttempt[]; complete: boolean }

export const successfulRequests = ({ requests, failed, uncertain }: RequestTotals) => requests - failed - uncertain

const base = '/agent/model-gateway/monitor'
export const loadRequestDetail = (id: string, signal: AbortSignal, routeId?: string): Promise<{ data: RequestDetail }> =>
  api('GET', base + '/requests/' + encodeURIComponent(id) + (routeId ? '?' + new URLSearchParams({ routeId }) : ''), undefined, { signal })

const hasRequestList = (data?: RequestList) => Array.isArray(data?.recent)
const hasRequestSummary = (data?: RequestSummary) => !!data?.range && Array.isArray(data.byModel)

export function useGatewayRequests(active: boolean, hours: number, route: string, caller: string, outcome: string, window: RequestWindow | null, reason?: RequestFailureReason, switched?: RequestSwitchFilter) {
  return useGatewayRequestView(hasRequestList, 'requests', active, hours, route, caller, outcome, window, reason, switched)
}

export function useGatewayRequestSummary(active: boolean, hours: number, route: string, caller: string, outcome: string, window: RequestWindow | null, reason?: RequestFailureReason) {
  return useGatewayRequestView(hasRequestSummary, 'request-summary', active, hours, route, caller, outcome, window, reason)
}

function useGatewayRequestView<T>(supports: (data?: T) => boolean, view: string, active: boolean, hours: number, route: string, caller: string, outcome: string, window: RequestWindow | null, reason?: RequestFailureReason, switched?: RequestSwitchFilter) {
  const [result, setResult] = useState<{ query: string; data?: T; failed?: boolean; unsupported?: boolean } | null>(null)
  const [retry, setRetry] = useState(0)
  const params = new URLSearchParams({ view, hours: String(hours) })
  if (route) params.set('routeId', route)
  if (caller) params.set('caller', caller)
  if (outcome) params.set('outcome', outcome)
  if (reason) params.set('reason', reason)
  if (switched) params.set('switch', switched)
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
        if (!signal.aborted) setResult(supports(data) ? { query, data } : { query, unsupported: true })
      } catch (error) {
        if (!signal.aborted) setResult(previous => ({ query, data: previous?.query === query ? previous.data : undefined, failed: true }))
        throw error
      }
    }, 30_000)
    return poll.stop
  }, [active, query, retry, supports])
  const pending = result?.query !== query
  return { data: result?.data, pending, failed: !pending && result?.failed, unsupported: !pending && result?.unsupported, retry: () => setRetry(value => value + 1) }
}
