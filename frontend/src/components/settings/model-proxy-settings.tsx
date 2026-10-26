import { useEffect, useState } from 'react'
import { Button, Input, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { ModelUsageStatistics, type UsageStatistics } from './model-usage-statistics'

export type ModelPrice = { input: number; output: number; cacheRead: number }
export type ModelProxyConfig = { dailyLimit: number | null; prices: Record<string, ModelPrice> }
type PriceDraft = Record<keyof ModelPrice, string>
export type ModelProxyDraft = { dailyLimit: string; prices: Record<string, PriceDraft> }
type Usage = { statistics?: UsageStatistics; day: string; timezone: string; requests: number; knownCost: number; unknown: number; pending: number; inputTokens: number; outputTokens: number; cacheReadTokens: number; recent: { id: string; role: string; model: string; started_ms: number; state: string; input_tokens: number | null; output_tokens: number | null; cost: number | null }[] }
const priceFields = ['input', 'output', 'cacheRead'] as const
export const proxyDraft = (config?: ModelProxyConfig): ModelProxyDraft => ({ dailyLimit: config?.dailyLimit?.toString() || '', prices: Object.fromEntries(Object.entries(config?.prices || {}).map(([model, rate]) => [model, { input: String(rate.input), output: String(rate.output), cacheRead: String(rate.cacheRead) }])) })
export const proxyConfig = (draft: ModelProxyDraft): ModelProxyConfig => ({ dailyLimit: draft.dailyLimit === '' ? null : Number(draft.dailyLimit), prices: Object.fromEntries(Object.entries(draft.prices).filter(([, rate]) => priceFields.some(key => rate[key] !== '')).map(([model, rate]) => [model, Object.fromEntries(priceFields.map(key => [key, Number(rate[key])])) as ModelPrice])) })
const validAmount = (text: string) => { const value = Number(text); return text !== '' && Number.isFinite(value) && value >= 0 && value <= 1000000 && Number(value.toFixed(6)) === value }
export const validProxyDraft = (draft: ModelProxyDraft) => (draft.dailyLimit === '' || validAmount(draft.dailyLimit) && Number(draft.dailyLimit) > 0) && Object.values(draft.prices).every(rate => priceFields.every(key => rate[key] === '') || priceFields.every(key => validAmount(rate[key])))

export function ModelProxySettings({ value, models, disabled, onChange, snapshot, active }: { active: boolean; value: ModelProxyDraft; models: string[]; disabled: boolean; onChange: (value: ModelProxyDraft) => void; snapshot: unknown }) {
  const { t, locale } = useI18n()
  const [days, setDays] = useState(7), [loading, setLoading] = useState(false)
  const [usage, setUsage] = useState<Usage | null>(null), [failed, setFailed] = useState(false), [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!active) return
    const abort = new AbortController()
    setFailed(false); setLoading(true)
    void api('GET', days === 7 ? '/agent/model-usage' : `/agent/model-usage?days=${days}`, undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) typeof data?.knownCost === 'number' ? setUsage(data) : setFailed(true) }).catch(() => { if (!abort.signal.aborted) setFailed(true) }).finally(() => { if (!abort.signal.aborted) setLoading(false) })
    return () => abort.abort()
  }, [active, snapshot, retry, days])
  const money = (amount: number) => new Intl.NumberFormat(locale, { style: 'currency', currency: 'CNY', minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(amount)
  const count = (amount: number) => new Intl.NumberFormat(locale).format(amount)
  return <fieldset className="agent-model-proxy" disabled={disabled}>
    <legend>{t('agent.proxy.title')}</legend>
    <p className="agent-settings-hint">{t('agent.proxy.scope')}</p>
    {usage && typeof usage.knownCost === 'number' ? <>
      <div className="agent-proxy-totals" role="status">
        <div><span>{t('agent.proxy.todayCost')}</span><strong>{money(usage.knownCost)}</strong></div>
        <div><span>{t('agent.proxy.requests')}</span><strong>{count(usage.requests)}</strong></div>
        <div><span>{t('agent.proxy.tokens')}</span><strong>{count(usage.inputTokens + usage.outputTokens)}</strong></div>
      </div>
      <p className="agent-settings-hint">{t('agent.proxy.period', { day: new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(usage.day + 'T00:00:00Z')), zone: usage.timezone })}</p>
      {usage.unknown > 0 && <p className="agent-settings-error" role="status">{t('agent.proxy.unknown', { count: count(usage.unknown) })}</p>}
      {usage.pending > 0 && <p className="agent-settings-hint">{t('agent.proxy.pending', { count: count(usage.pending) })}</p>}
      {usage.recent.length > 0 && <details className="agent-model-advanced"><summary>{t('agent.proxy.recent')}</summary><ul className="agent-proxy-calls">{usage.recent.map(call => <li key={call.id}><div><strong>{call.model}</strong><span>{t('agent.models.role.' + call.role)} · {new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', timeZone: usage.timezone }).format(call.started_ms)}</span></div><span>{t('agent.proxy.state.' + call.state)}</span><strong>{call.cost === null ? t('agent.proxy.costUnknown') : money(call.cost)}</strong></li>)}</ul></details>}
    </> : !failed && <Spin size="small" />}
    {failed && <div role="alert"><p>{t('agent.proxy.loadFailed')}</p><Button onClick={() => setRetry(v => v + 1)}>{t('agent.retry')}</Button></div>}
    <ModelUsageStatistics statistics={usage?.statistics} days={days} onDaysChange={setDays} loading={loading} disabled={disabled} />
    <div className="agent-settings-field"><label htmlFor="agent-proxy-limit">{t('agent.proxy.dailyLimit')}</label><Input id="agent-proxy-limit" type="number" min="0.000001" max={1000000} step="0.000001" value={value.dailyLimit} onChange={event => onChange({ ...value, dailyLimit: event.target.value })} placeholder={t('agent.proxy.unlimited')} disabled={disabled} /></div>
    <p className="agent-settings-hint">{t('agent.proxy.limitHint')}</p>
    <details className="agent-model-advanced"><summary>{t('agent.proxy.prices')}</summary><p className="agent-settings-hint">{t('agent.proxy.priceHint')}</p><div className="agent-proxy-prices">{Array.from(new Set([...models, ...Object.keys(value.prices)])).filter(Boolean).map((model, index) => {
      const rate = value.prices[model] || { input: '', output: '', cacheRead: '' }
      const partial = priceFields.some(key => rate[key] !== '')
      return <div className="agent-proxy-price" key={model}><strong>{model}</strong><div className="agent-proxy-price-fields">{priceFields.map(key => <div className="agent-settings-field" key={key}><label htmlFor={`agent-price-${index}-${key}`}>{t('agent.proxy.price.' + key)}</label><Input id={`agent-price-${index}-${key}`} aria-label={t('agent.proxy.priceLabel', { model, kind: t('agent.proxy.price.' + key) })} type="number" min={0} max={1000000} step="0.000001" required={partial} value={rate[key]} placeholder={t('agent.proxy.unpriced')} disabled={disabled} onChange={event => onChange({ ...value, prices: { ...value.prices, [model]: { ...rate, [key]: event.target.value } } })} /></div>)}</div></div>
    })}</div></details>
  </fieldset>
}
