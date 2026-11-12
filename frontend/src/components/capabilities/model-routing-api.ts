import { useEffect, useState } from 'react'
import { api } from '../../api'
import { pollWhileVisible } from '../../visible-poll'
export const routingStrategies = ['smart', 'order', 'drain', 'rotate', 'usage', 'pace', 'weight', 'fast', 'cheap'] as const
export type RoutingStrategy = typeof routingStrategies[number]
export type PriceRule = { mode: '' | 'inherit' | 'tokens' | 'free' | 'quota' | 'unknown'; confirmed?: boolean; price: { input_per_million: number; output_per_million: number; cache_read_per_million: number } }
export type SourcePricing = { accountStrategy?: RoutingStrategy; default: PriceRule; models?: Record<string, PriceRule>; multiplier?: number; timeRule?: '' | 'deepseek' | 'ollama-deepseek' }
export type RoutingStatus = { now: number; available: number; channels: { sourceId: string; model: string; account: string; kind: string; ready: boolean; remaining: number | null; resetAt: number | null; expiresAt: number | null; restUntil: number | null; measuredAt: number | null; recentTokens: number }[] }
export function useRoutingStatus(model: string, active: boolean, revision: string) {
  const [result, setResult] = useState<{ key: string; data: RoutingStatus } | null>(null), [failed, setFailed] = useState(false), [retry, setRetry] = useState(0)
  const key = model + ':' + revision
  useEffect(() => {
    if (!active || !model) return
    const poll = pollWhileVisible(async signal => {
      try { const { data } = await api('GET', '/agent/model-gateway/catalog/routing?model=' + encodeURIComponent(model), undefined, { signal }); if (!signal.aborted) { setResult({ key, data }); setFailed(false) } }
      catch (error) { if (!signal.aborted) setFailed(true); throw error }
    }, 30_000)
    return poll.stop
  }, [active, model, key, retry])
  return { data: result?.key === key ? result.data : undefined, failed, retry: () => setRetry(value => value + 1) }
}
