import type { ModelProxyDraft, PriceDraft, ProxyUsage } from './model-proxy-settings'
import type { ModelCharge } from './model-charges'
import type { UsageTotals, UsageStatistics, UsagePoint } from './model-usage-statistics'

export type GatewayPrice = { input_per_million: number; output_per_million: number; cache_read_per_million: number }
export type GatewayConfiguration = { currency: string; timezone: string; dailyLimit: number | null; pricing: { default: GatewayPrice; models: Record<string, GatewayPrice> } }
export type GatewayDraft = ModelProxyDraft & { timezone: string; defaultPrice: PriceDraft }
export type UsageSource = '' | 'rsi' | 'other'
export type GatewayGroup = { source?: UsageSource; day: string; role: string; model: string; currency: string; requests: number; inputTokens: number; outputTokens: number; cacheReadTokens: number; pending: number; unknown: number; usageUnknown: number; failed: number; cost: string; hour?: number }
export type GatewayCall = { source?: UsageSource; sessionId?: string; id: string; day: string; model: string; role: string; state: string; currency: string; cost: string | null; startedMs: number; inputTokens: number | null; outputTokens: number | null; cacheReadTokens: number | null; errorCode: string; httpStatus: number; reconciliation: string }
export type GatewayUsage = { source?: UsageSource; day: string; timezone: string; from: string; to: string; days: number; today: GatewayGroup[]; groups: GatewayGroup[]; hourly: GatewayGroup[]; recent: GatewayCall[] }
const draftPrice = (price: GatewayPrice, currency: string): PriceDraft => ({ currency, input: String(price.input_per_million), output: String(price.output_per_million), cacheRead: String(price.cache_read_per_million) })
export const gatewayDraft = (config: GatewayConfiguration): GatewayDraft => ({ currency: config.currency, timezone: config.timezone, dailyLimit: config.dailyLimit?.toString() ?? '', defaultPrice: draftPrice(config.pricing.default, config.currency), prices: Object.fromEntries(Object.entries(config.pricing.models || {}).map(([model, price]) => [model, draftPrice(price, config.currency)])) })
const rate = (price: PriceDraft): GatewayPrice => ({ input_per_million: Number(price.input), output_per_million: Number(price.output), cache_read_per_million: Number(price.cacheRead) })
export const gatewayConfiguration = (draft: GatewayDraft): GatewayConfiguration => ({ currency: draft.currency, timezone: draft.timezone.trim(), dailyLimit: draft.dailyLimit === '' ? null : Number(draft.dailyLimit), pricing: { default: rate(draft.defaultPrice), models: Object.fromEntries(Object.entries(draft.prices).filter(([, price]) => [price.input, price.output, price.cacheRead].some(value => value !== '')).map(([model, price]) => [model, rate(price)])) } })
const validAmount = (text: string) => text.trim() !== '' && Number.isFinite(Number(text)) && Number(text) >= 0 && Number(text) <= 1_000_000
export const validGatewayDraft = (draft: GatewayDraft) => /^[A-Z]{3}$/.test(draft.currency) && !!draft.timezone.trim() && (draft.dailyLimit === '' || validAmount(draft.dailyLimit)) && Object.values(draft.prices).filter(price => [price.input, price.output, price.cacheRead].some(value => value !== '')).length <= 200 && [draft.defaultPrice, ...Object.values(draft.prices)].every(price => [price.input, price.output, price.cacheRead].every(value => value === '') || validAmount(price.input) && validAmount(price.output) && (price.cacheRead === '' || validAmount(price.cacheRead)))

// Keep the ledger's nanounits intact when merging currencies and model series.
const nano = (amount: string) => { const [whole, fraction = ''] = amount.split('.'); return BigInt(whole) * 1_000_000_000n + BigInt(fraction.padEnd(9, '0')) }
const amount = (value: bigint) => `${value / 1_000_000_000n}.${String(value % 1_000_000_000n).padStart(9, '0')}`
export function mergeCharges(charges: ModelCharge[]): ModelCharge[] {
  const totals = new Map<string, bigint>()
  for (const charge of charges) totals.set(charge.currency, (totals.get(charge.currency) || 0n) + nano(charge.amount))
  return [...totals].sort(([a], [b]) => a.localeCompare(b)).map(([currency, value]) => ({ currency, amount: amount(value) }))
}
const empty = (): UsageTotals => ({ requests: 0, inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, totalTokens: 0, unknown: 0, pending: 0, failed: 0, missingUsage: 0, estimated: 0, charges: [], estimatedCharges: [] })
function totals(groups: GatewayGroup[], currency?: string): UsageTotals {
  const value = empty(), charges: ModelCharge[] = []
  for (const row of groups) {
    for (const key of ['requests', 'inputTokens', 'outputTokens', 'cacheReadTokens', 'unknown', 'pending', 'failed'] as const) value[key] += row[key]
    value.missingUsage += row.usageUnknown
    if (row.requests > row.pending + row.unknown) charges.push({ currency: row.currency, amount: row.cost })
  }
  value.totalTokens = value.inputTokens + value.outputTokens
  value.charges = mergeCharges(charges)
  if (!groups.length && currency) value.charges = [{ currency, amount: '0.000000000' }]
  return value
}
export function gatewayUsage(raw: GatewayUsage, currency: string): ProxyUsage {
  const models = [...new Set(raw.groups.map(row => row.model))].map(model => ({ ...totals(raw.groups.filter(row => row.model === model)), model })).sort((a, b) => b.totalTokens - a.totalTokens || a.model.localeCompare(b.model))
  const series = models.slice(0, 4).map(row => row.model)
  const point = (groups: GatewayGroup[]): UsagePoint => ({ ...totals(groups), models: [...series.map(model => ({ ...totals(groups.filter(row => row.model === model)), model })), ...(groups.some(row => !series.includes(row.model)) ? [{ ...totals(groups.filter(row => !series.includes(row.model))), model: null }] : [])].filter(row => row.requests > 0) })
  const end = raw.to || raw.day
  const first = new Date(end + 'T00:00:00Z'); first.setUTCDate(first.getUTCDate() - 89)
  const dailyStart = raw.from > first.toISOString().slice(0, 10) ? raw.from : first.toISOString().slice(0, 10)
  const daily: UsageStatistics['daily'] = []
  for (let date = new Date(dailyStart + 'T00:00:00Z'); date.toISOString().slice(0, 10) <= end; date.setUTCDate(date.getUTCDate() + 1)) {
    const day = date.toISOString().slice(0, 10)
    daily.push({ ...point(raw.groups.filter(row => row.day === day)), day })
  }
  const statistics: UsageStatistics = { days: raw.days, startDay: raw.from, endDay: end, dailyStartDay: dailyStart, total: totals(raw.groups, currency), daily, hourly: Array.from({ length: 24 }, (_, hour) => ({ ...point((raw.hourly || []).filter(row => row.hour === hour)), hour })), models: models.slice(0, 200), modelsTruncated: models.length > 200, seriesModels: series, seriesTruncated: models.length > 4 }
  return { ...totals(raw.today, currency), day: raw.day, timezone: raw.timezone, statistics, recent: raw.recent.map(call => ({ id: call.id, model: call.model, role: call.role, source: call.source || (call.role.startsWith('rsi_') || call.sessionId?.startsWith('rsi-') ? 'rsi' : 'other'), started_ms: call.startedMs, state: call.state, cost_source: 'local', charges: call.cost === null ? [] : [{ currency: call.currency, amount: call.cost }], estimatedCharges: [], currency: call.currency, errorCode: call.errorCode, reconciliation: call.reconciliation })) }
}
