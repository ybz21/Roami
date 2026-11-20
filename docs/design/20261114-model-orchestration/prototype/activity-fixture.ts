import type { GatewayRequest, RequestTotals } from '../../../../frontend/src/components/capabilities/gateway-request-api'
import type { MonitorEvent } from '../../../../frontend/src/components/capabilities/model-monitor-api'

const minute = 60_000
const hour = minute * 60
export const now = Date.now()
const day = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(now)
export const traceCases = {
  blocked: { label: ['选路被拒', 'Blocked before dispatch'], outcome: 'blocked', status: 503, attempts: [], error: 'MODEL_ROUTE_NO_AVAILABLE_MEMBER', blocks: { pricing: 1, directory: 1 } },
  exhausted: { label: ['候选用尽', 'Candidates exhausted'], outcome: 'exhausted', status: 503, attempts: [429, 402], error: 'MODEL_ROUTE_NO_AVAILABLE_MEMBER' },
  fallback: { label: ['切换后恢复', 'Recovered after fallback'], outcome: 'recovered', status: 200, attempts: [429, 200] },
  stream: { label: ['输出中断', 'Stream interrupted'], outcome: 'interrupted', status: 200, attempts: [200], error: 'MODEL_UPSTREAM_STREAM_INTERRUPTED' },
  success: { label: ['直接成功', 'Direct success'], outcome: 'success', status: 200, attempts: [200] },
} as const

const origins = [
  { sourceId: 'openrouter', model: 'ernie-flash:free' },
  { sourceId: 'workbuddy', model: 'hy4-flash' },
]
const attemptError: Record<number, string> = { 429: 'MODEL_UPSTREAM_RATE_LIMITED', 402: 'MODEL_UPSTREAM_QUOTA_EXHAUSTED' }
const makeTrace = (key: keyof typeof traceCases, offset: number, suffix = '', members = origins) => {
  const entry = traceCases[key]
  const requestId = key + suffix
  const at = now - offset * minute
  const attempts = entry.attempts.map((status, index) => ({
    attempt: index + 1, ...members[index], status, at: at + index * 850,
    success: status === 200 && key !== 'stream', error: attemptError[status] || (key === 'stream' ? traceCases.stream.error : undefined),
    billing: status === 200 && key !== 'stream' ? { state: 'settled', cost: '0.000000000', currency: 'CNY' } : { state: 'unknown' },
  }))
  const last = attempts[attempts.length - 1]
  const request: GatewayRequest = {
    requestId, at, routeId: 'free', model: 'free', caller: key === 'blocked' ? 'claude' : 'roami',
    outcome: entry.outcome, sourceId: last?.sourceId || '', upstreamModel: last?.model,
    status: entry.status, durationMs: attempts.length ? 1100 + attempts.length * 570 : 8,
    attempts: attempts.length, switch: attempts.length > 1 ? (attempts[0].sourceId === last?.sourceId ? 'model' : 'source') : undefined,
    error: 'error' in entry ? entry.error : undefined, blocks: 'blocks' in entry ? entry.blocks : undefined,
    revision: 'demo-1',
  }
  return { request, attempts, complete: true }
}
export const traces = [
  makeTrace('fallback', 3), makeTrace('blocked', 9), makeTrace('exhausted', 16), makeTrace('stream', 27), makeTrace('success', 41),
  makeTrace('fallback', 52, '-same-source', [origins[1], { sourceId: 'workbuddy', model: 'deepseek-flash' }]),
  ...Array.from({ length: 18 }, (_, i) => makeTrace(i % 5 === 0 ? 'fallback' : i % 4 === 0 ? 'exhausted' : 'success', 65 + i * 75, '-' + i)),
]
const requestTotals = (rows: GatewayRequest[]): RequestTotals => ({
  requests: rows.length,
  failed: rows.filter(row => ['blocked', 'exhausted', 'interrupted', 'failed'].includes(row.outcome)).length,
  recovered: rows.filter(row => row.outcome === 'recovered').length,
  uncertain: 0,
  sameSource: rows.filter(row => row.switch === 'model').length,
  crossSource: rows.filter(row => row.switch === 'source').length,
})
export const requestObservation = {
  ...requestTotals(traces.filter(row => row.request.at >= now - hour).map(row => row.request)),
  latest: traces[0].request, latestSwitch: traces[0].request,
}

export function requestMonitor(query: URLSearchParams) {
  const end = Number(query.get('end')) || now
  const hours = Number(query.get('hours')) || 24
  const start = end - hours * hour
  const scope = traces.map(row => row.request).filter(row =>
    row.at >= start && row.at < end &&
    (!query.get('routeId') || row.routeId === query.get('routeId')) &&
    (!query.get('caller') || row.caller === query.get('caller')))
  const selected = scope.filter(row =>
    (!query.has('from') || row.at >= Number(query.get('from'))) &&
    (!query.has('to') || row.at < Number(query.get('to'))))
  const outcomes: Record<string, number> = {}
  for (const row of selected) outcomes[row.outcome] = (outcomes[row.outcome] || 0) + 1
  const points = Array.from({ length: 12 }, (_, index) => {
    const from = Math.floor(start + index * hours * hour / 12)
    const to = Math.floor(start + (index + 1) * hours * hour / 12)
    return { from, to, totals: requestTotals(scope.filter(row => row.at >= from && row.at < to)) }
  })
  return {
    now: end, totals: requestTotals(selected), routes: { free: 'free' },
    callers: { roami: true, 'claude': true }, points, outcomes,
    recent: selected.filter(row => !query.get('outcome') || row.outcome === query.get('outcome')),
  }
}

type PoolEvent = MonitorEvent & { requestId?: string }
const events: PoolEvent[] = traces.flatMap(({ request, attempts }) => attempts.map(attempt => ({ ...attempt, requestId: request.requestId }))).map((row, index) => ({
  ...row, sequence: index + 1, error: row.error || '', durationMs: 1150 + index * 30,
  firstTokenMs: row.success ? 260 + index * 20 : null, tokensPerSecond: row.success ? 57 + index : null,
  quality: '',
}))
export function checkSource(sourceId: string, model: string, rule: string) {
  const event = { sourceId, model, quality: 'pass', qualityRule: rule, sequence: events.length + 1, at: now, success: true, status: 200, error: '', durationMs: 960, firstTokenMs: 260, tokensPerSecond: 72 }
  events.push(event)
  return event
}
function sourceTotals(rows: typeof events) {
  const graded = rows.filter(row => row.quality)
  const success = rows.filter(row => row.success)
  const time = success.map(row => row.firstTokenMs || 0).sort((a, b) => a - b)
  const speed = success.map(row => row.tokensPerSecond || 0).sort((a, b) => a - b)
  return { requests: rows.length, failed: rows.length - success.length, success: rows.length ? success.length / rows.length : null, firstTokenP95: time[Math.ceil(time.length * .95) - 1] ?? null, outputP50: speed[Math.floor(speed.length / 2)] ?? null, quality: graded.length ? graded.filter(row => row.quality === 'pass').length / graded.length : null, graded: graded.length }
}
export function poolMemberMetrics(ids: ReadonlySet<string>, sourceId: string, model: string) {
  const rows = events.filter(row => row.requestId && ids.has(row.requestId) && row.sourceId === sourceId && row.model === model)
  const totals = sourceTotals(rows)
  return { attempts: totals.requests, successes: totals.requests - totals.failed, firstTokenP95: totals.firstTokenP95, outputP50: totals.outputP50 }
}
export function sourceMonitor(query: URLSearchParams) {
  const hours = Number(query.get('hours')) || 24
  const start = now - hours * hour
  const rows = events.filter(row => row.at >= start && (!query.get('sourceId') || row.sourceId === query.get('sourceId')) && (!query.get('model') || row.model === query.get('model')))
  const ids = [...new Set(rows.map(row => row.sourceId))]
  const points = Array.from({ length: 24 }, (_, i) => {
    const at = start + i * hours * hour / 24
    return { at, totals: sourceTotals(rows.filter(row => row.at >= at && row.at < at + hours * hour / 24)) }
  })
  return {
    now, hours, totals: sourceTotals(rows), points,
    sources: ids.map(sourceId => ({ sourceId, totals: sourceTotals(rows.filter(row => row.sourceId === sourceId)) })),
    models: Object.fromEntries(ids.map(id => [id, Object.fromEntries(rows.filter(row => row.sourceId === id).map(row => [row.model, true]))])),
    events: rows.filter(row => !row.success || row.quality === 'fail'),
    storage: { records: events.length, maxRecords: 20000, bytes: events.length * 256, maxBytes: 67108864, retentionHours: 24, expired: 0, evicted: 0, dropped: 0 },
  }
}

const calls = traces.slice(0, 5).map(({ request }, index) => {
  const success = ['success', 'recovered'].includes(request.outcome)
  return {
    id: request.requestId, requestId: request.requestId, day,
    sourceId: request.sourceId, routeId: request.routeId, model: request.upstreamModel || request.model,
    startedMs: request.at, finishedMs: request.at + request.durationMs, role: 'main', agentKind: request.caller,
    source: 'other', state: success ? 'known' : 'failed', currency: 'CNY', cost: '0.000000000',
    httpStatus: request.status, errorCode: request.error || '', reconciliation: '', priceStatus: 'free',
    inputTokens: success ? 3600 + index * 650 : null, outputTokens: success ? 740 : null, cacheReadTokens: success ? 500 : null,
  }
})
export function reconcileCall(id: string, amount: number, reason: string) {
  const row = calls.find(call => call.id === id)
  if (row) Object.assign(row, { state: 'known', cost: amount.toFixed(9), reconciliation: reason })
}
export function usage(query: URLSearchParams) {
  const localHour = (ms: number) => Number(new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Shanghai', hour: '2-digit', hourCycle: 'h23' }).format(ms))
  const fields = ['agentKind', 'model', 'source', 'state', 'day', 'sourceId'] as const
  const scoped = calls.filter(row => fields.every(key => !query.get(key) || query.get(key) === row[key]) && (!query.has('unattributed') || !row.sourceId))
  const recent = scoped.filter(row => (!query.has('hour') || localHour(row.startedMs) === Number(query.get('hour'))) &&
    (!query.get('q') || [row.model, row.id].some(text => text.toLowerCase().includes(query.get('q')!.toLowerCase()))))
  const grouping = (rows: typeof calls) => rows.map(row => ({ ...row, hour: localHour(row.startedMs), requests: 1, inputTokens: row.inputTokens || 0, outputTokens: row.outputTokens || 0, cacheReadTokens: row.cacheReadTokens || 0, pending: 0, unknown: 0, usageUnknown: row.inputTokens === null ? 1 : 0, failed: row.state === 'failed' ? 1 : 0 }))
  const days = Number(query.get('days')) || 1
  const from = query.get('start') || new Date(Date.parse(day) - (days - 1) * 24 * hour).toISOString().slice(0, 10)
  const to = query.get('end') || day
  const rows = from <= day && to >= day ? recent : []
  return { day, timezone: 'Asia/Shanghai', accountingTimezone: 'Asia/Shanghai', from, to, days, dailyAggregated: days > 2, detailRetentionHours: 48, today: grouping(calls), groups: grouping(rows), hourly: grouping(rows), recent: rows, hourlyDay: day, nowMs: now, archived: 0, page: 1, pageSize: 50, total: rows.length, options: { sources: ['openrouter', 'workbuddy'], agents: ['roami', 'claude'], models: [...new Set(calls.map(row => row.model))] } }
}
