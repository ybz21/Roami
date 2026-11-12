import { useEffect, useState } from 'react'
import { api } from '../../api'
import { pollWhileVisible } from '../../visible-poll'
export type MonitorTotals = { requests: number; failed: number; success: number | null; firstTokenP95: number | null; outputP50: number | null; quality: number | null; graded: number }
export type MonitorEvent = { sequence: number; at: number; sourceId: string; model: string; success: boolean; status: number; error: string; durationMs: number; firstTokenMs: number | null; tokensPerSecond: number | null; quality: string; qualityRule?: string }
export type MonitorData = { now: number; hours: number; totals: MonitorTotals; sources: { sourceId: string; totals: MonitorTotals }[]; models: Record<string, Record<string, boolean>>; points: { at: number; totals: MonitorTotals }[]; events: MonitorEvent[]; storage: { records: number; maxRecords: number; bytes: number; maxBytes: number; retentionHours: number; expired: number; evicted: number; dropped: number } }
export function useModelMonitor(active: boolean, hours: number, source: string, model: string, version: number) {
  const [result, setResult] = useState<{ key: string; data: MonitorData } | null>(null), [failed, setFailed] = useState(false), [retry, setRetry] = useState(0)
  const query = new URLSearchParams({ hours: String(hours), ...(source ? { sourceId: source } : {}), ...(model ? { model } : {}) }).toString()
  useEffect(() => {
    if (!active) return
    const poll = pollWhileVisible(async signal => {
      try { const { data } = await api('GET', '/agent/model-gateway/monitor?' + query, undefined, { signal }); if (!signal.aborted) { setResult({ key: query, data }); setFailed(false) } }
      catch (cause) { if (!signal.aborted) setFailed(true); throw cause }
    }, 30_000)
    return poll.stop
  }, [active, query, version, retry])
  return { data: result?.key === query ? result.data : undefined, failed, retry: () => setRetry(value => value + 1) }
}
