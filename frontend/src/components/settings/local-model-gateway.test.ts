import { expect, it } from 'vitest'
import { gatewayConfiguration, gatewayDraft, gatewayUsage, validGatewayDraft, type GatewayConfiguration, type GatewayGroup, type GatewayUsage } from './local-model-gateway'

const config: GatewayConfiguration = { currency: 'CNY', timezone: 'Asia/Shanghai', dailyLimit: 0, pricing: { default: { input_per_million: 1, output_per_million: 2, cache_read_per_million: .5 }, models: { fixture: { input_per_million: .123456789, output_per_million: 4, cache_read_per_million: 0 } } } }
const group: GatewayGroup = { day: '2026-10-29', role: 'main', model: 'fixture', currency: 'CNY', requests: 1, inputTokens: 10, outputTokens: 5, cacheReadTokens: 2, pending: 0, unknown: 0, usageUnknown: 0, failed: 0, cost: '0.000000001' }
const usage = (groups: GatewayGroup[]): GatewayUsage => ({ day: group.day, timezone: 'Asia/Shanghai', from: group.day, to: group.day, days: 1, today: groups, groups, hourly: groups.map(row => ({ ...row, hour: 9 })), recent: [] })

it('round trips zero limits, default prices and precise model rates', () => {
  const draft = gatewayDraft(config)
  expect(draft.dailyLimit).toBe('0')
  expect(validGatewayDraft(draft)).toBe(true)
  expect(gatewayConfiguration(draft)).toEqual(config)
  expect(gatewayConfiguration({ ...draft, dailyLimit: '' }).dailyLimit).toBeNull()
  expect(validGatewayDraft({ ...draft, dailyLimit: '-1' })).toBe(false)
  expect(validGatewayDraft({ ...draft, defaultPrice: { ...draft.defaultPrice, input: 'NaN' } })).toBe(false)
})

it('merges role and model groups without losing nanounits or currencies', () => {
  const result = gatewayUsage(usage([group, { ...group, role: 'worker' }, { ...group, model: 'another', currency: 'USD', cost: '2.000000000' }]), 'CNY')
  expect(result.charges).toEqual([{ currency: 'CNY', amount: '0.000000002' }, { currency: 'USD', amount: '2.000000000' }])
  expect(result.statistics?.total.totalTokens).toBe(45)
  expect(result.statistics?.models.find(row => row.model === 'fixture')?.requests).toBe(2)
  expect(result.statistics?.hourly?.[9].requests).toBe(3)
  expect(result.statistics?.daily[0].requests).toBe(3)
})

it('keeps unknown costs and missing usage visible after reconciliation', () => {
  const unknown = gatewayUsage(usage([{ ...group, unknown: 1, usageUnknown: 1, cost: '0.000000000' }]), 'CNY')
  expect(unknown.charges).toEqual([])
  expect(unknown.unknown).toBe(1)
  expect(unknown.statistics?.total.missingUsage).toBe(1)
  const reconciled = gatewayUsage(usage([{ ...group, usageUnknown: 1, cost: '.750000000' }]), 'CNY')
  expect(reconciled.charges).toEqual([{ currency: 'CNY', amount: '0.750000000' }])
  expect(reconciled.statistics?.total.missingUsage).toBe(1)
})


it('labels historical RSI sessions and new roles without guessing untagged requests', () => {
  const call = { id: '1', day: group.day, model: 'fixture', role: 'main', state: 'known', currency: 'CNY', cost: '0.000000001', startedMs: 1, inputTokens: 10, outputTokens: 5, cacheReadTokens: 2, errorCode: '', httpStatus: 200, reconciliation: '' }
  const raw = { ...usage([group]), recent: [call, { ...call, sessionId: 'rsi-legacy' }, { ...call, role: 'rsi_artifact_b' }, { ...call, role: 'rsiXworker', sessionId: 'rsiXlegacy' }] }
  expect(gatewayUsage(raw, 'CNY').recent.map(row => row.source)).toEqual(['other', 'rsi', 'rsi', 'other'])
})

it('keeps an unset default price separate from an explicitly configured zero price', () => {
  const unset = { ...config, pricing: { ...config.pricing, defaultConfigured: false, default: { input_per_million: 0, output_per_million: 0, cache_read_per_million: 0 } } }
  const draft = gatewayDraft(unset)
  expect(draft.defaultPrice.input).toBe('')
  expect(gatewayConfiguration(draft).pricing.defaultConfigured).toBe(false)
  const free = { ...draft, defaultPrice: { ...draft.defaultPrice, input: '0', output: '0', cacheRead: '0' } }
  expect(gatewayConfiguration(free).pricing.defaultConfigured).toBe(true)
})
