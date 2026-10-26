import { useEffect, useState } from 'react'
import { Button, Input, Select, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { ModelCharges, type ModelCharge } from './model-charges'
import { ModelUsageStatistics, type UsageStatistics } from './model-usage-statistics'

export type ModelPrice = { currency: string; input: number; output: number; cacheRead: number | null }
export type ModelProxyConfig = { dailyLimit: number | null; currency: string; prices?: Record<string, ModelPrice> }
type PriceDraft = { currency: string; input: string; output: string; cacheRead: string }
export type ModelProxyDraft = { dailyLimit: string; currency: string; prices: Record<string, PriceDraft> }
type Usage = { statistics?: UsageStatistics; day: string; timezone: string; requests: number; charges: ModelCharge[]; localCharges?: ModelCharge[]; estimatedCharges: ModelCharge[]; unknown: number; pending: number; inputTokens: number; outputTokens: number; cacheReadTokens: number; recent: { id: string; role: string; model: string; started_ms: number; state: string; cost_source: string; charges: ModelCharge[]; localCharges?: ModelCharge[]; estimatedCharges: ModelCharge[] }[] }
export const proxyDraft = (config?: ModelProxyConfig): ModelProxyDraft => ({ dailyLimit: config?.dailyLimit?.toString() || '', currency: config?.currency || (config ? 'CNY' : 'USD'), prices: Object.fromEntries(Object.entries(config?.prices || {}).map(([model, price]) => [model, { currency: price.currency || config?.currency || 'CNY', input: String(price.input), output: String(price.output), cacheRead: price.cacheRead?.toString() ?? '' }])) })
const priceFields = ['input', 'output', 'cacheRead'] as const
const hasPrice = (price: PriceDraft) => priceFields.some(key => price[key] !== '')
export const proxyConfig = (draft: ModelProxyDraft): ModelProxyConfig => ({ dailyLimit: draft.dailyLimit === '' ? null : Number(draft.dailyLimit), currency: draft.currency, prices: Object.fromEntries(Object.entries(draft.prices).filter(([, price]) => hasPrice(price)).map(([model, price]) => [model, { currency: price.currency, input: Number(price.input), output: Number(price.output), cacheRead: price.cacheRead === '' ? null : Number(price.cacheRead) }])) })
const validAmount = (text: string) => { const value = Number(text); return text !== '' && Number.isFinite(value) && value >= 0 && value <= 1000000 && Number(value.toFixed(6)) === value }
export const validProxyDraft = (draft: ModelProxyDraft) => (draft.dailyLimit === '' || validAmount(draft.dailyLimit) && Number(draft.dailyLimit) > 0) && /^[A-Z]{3}$/.test(draft.currency) && Object.values(draft.prices).filter(hasPrice).length <= 32 && Object.values(draft.prices).every(price => !hasPrice(price) || /^[A-Z]{3}$/.test(price.currency) && validAmount(price.input) && validAmount(price.output) && (price.cacheRead === '' || validAmount(price.cacheRead)))

export function ModelProxySettings({ value, models, disabled, onChange, snapshot, active }: { active: boolean; value: ModelProxyDraft; models: string[]; disabled: boolean; onChange: (value: ModelProxyDraft) => void; snapshot: unknown }) {
  const { t, locale } = useI18n()
  const [selectedDay, setSelectedDay] = useState('')
  const [days, setDays] = useState(7), [loading, setLoading] = useState(false)
  const [usage, setUsage] = useState<Usage | null>(null), [failed, setFailed] = useState(false), [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!active) return
    const abort = new AbortController()
    setFailed(false); setLoading(true)
    const path = days === 7 ? '/agent/model-usage' : `/agent/model-usage?days=${days}${days === 1 && selectedDay ? '&day=' + encodeURIComponent(selectedDay) : ''}`
    void api('GET', path, undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) Array.isArray(data?.charges) ? setUsage(data) : setFailed(true) }).catch(() => { if (!abort.signal.aborted) setFailed(true) }).finally(() => { if (!abort.signal.aborted) setLoading(false) })
    return () => abort.abort()
  }, [active, snapshot, retry, days, selectedDay])
  const count = (amount: number) => new Intl.NumberFormat(locale).format(amount)
  return <fieldset className="agent-model-proxy" disabled={disabled}>
    <legend>{t('agent.proxy.title')}</legend>
    <p className="agent-settings-hint">{t('agent.proxy.scope')}</p>
    <details className="agent-model-advanced"><summary>{t('agent.proxy.prices')}</summary><p className="agent-settings-hint">{t('agent.proxy.priceHint')}</p><div className="agent-proxy-prices">{Array.from(new Set([...models, ...Object.keys(value.prices)])).filter(Boolean).map((model, index) => {
      const price = value.prices[model] || { currency: value.currency, input: '', output: '', cacheRead: '' }
      const update = (patch: Partial<PriceDraft>) => onChange({ ...value, prices: { ...value.prices, [model]: { ...price, ...patch } } })
      return <div className="agent-proxy-price" key={model}><div className="agent-usage-toolbar"><strong>{model}</strong>{hasPrice(price) && <button type="button" className="tt-act danger" disabled={disabled} aria-label={t('agent.proxy.removePrice', { model })} onClick={() => { const prices = { ...value.prices }; delete prices[model]; onChange({ ...value, prices }) }}>{t('agent.proxy.remove')}</button>}</div><div className="agent-proxy-price-fields">
        <div className="agent-settings-field"><label htmlFor={`agent-price-${index}-currency`}>{t('agent.proxy.price.currency')}</label><Select id={`agent-price-${index}-currency`} aria-label={t('agent.proxy.priceCurrencyLabel', { model })} value={price.currency} disabled={disabled} virtual={false} options={Array.from(new Set(['USD', 'CNY', 'EUR', 'GBP', 'JPY', price.currency])).sort().map(currency => ({ value: currency, label: currency }))} onChange={currency => update({ currency })} /></div>
        {priceFields.map(key => <div className="agent-settings-field" key={key}><label htmlFor={`agent-price-${index}-${key}`}>{t('agent.proxy.price.' + key)}</label><Input id={`agent-price-${index}-${key}`} aria-label={t('agent.proxy.priceLabel', { model, kind: t('agent.proxy.price.' + key) })} type="number" min={0} max={1000000} step="0.000001" value={price[key]} disabled={disabled} placeholder={t(key === 'cacheRead' ? 'agent.proxy.cacheDefault' : 'agent.proxy.notSet')} onChange={event => update({ [key]: event.target.value })} /></div>)}
      </div></div>
    })}</div></details>
    {usage && Array.isArray(usage.charges) ? <>
      <div className="agent-proxy-totals" role="status">
        <div><span>{t('agent.proxy.todayCost')}</span><strong><ModelCharges charges={usage.charges} localCharges={usage.localCharges} estimatedCharges={usage.estimatedCharges} incomplete={usage.unknown > 0 || usage.pending > 0} /></strong></div>
        <div><span>{t('agent.proxy.requests')}</span><strong>{count(usage.requests)}</strong></div>
        <div><span>{t('agent.proxy.tokens')}</span><strong>{count(usage.inputTokens + usage.outputTokens)}</strong></div>
      </div>
      <p className="agent-settings-hint">{t('agent.proxy.period', { day: new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(usage.day + 'T00:00:00Z')), zone: usage.timezone })}</p>
      {usage.unknown > 0 && <p className="agent-settings-error" role="status">{t('agent.proxy.unknown', { count: count(usage.unknown) })}</p>}
      {usage.pending > 0 && <p className="agent-settings-hint">{t('agent.proxy.pending', { count: count(usage.pending) })}</p>}
      {usage.recent.length > 0 && <details className="agent-model-advanced"><summary>{t('agent.proxy.recent')}</summary><ul className="agent-proxy-calls">{usage.recent.map(call => <li key={call.id}><div><strong>{call.model}</strong><span>{t('agent.models.role.' + call.role)} · {new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', timeZone: usage.timezone }).format(call.started_ms)}</span></div><span>{t(call.cost_source === 'estimate' ? (call.localCharges?.length ? 'agent.proxy.localEstimate' : 'agent.proxy.estimate') : 'agent.proxy.state.' + call.state)}</span><strong>{call.cost_source === 'not_sent' ? t('agent.proxy.notSent') : <ModelCharges charges={call.charges} localCharges={call.localCharges} estimatedCharges={call.estimatedCharges} />}</strong></li>)}</ul></details>}
    </> : !failed && <Spin size="small" />}
    {failed && <div role="alert"><p>{t('agent.proxy.loadFailed')}</p><Button onClick={() => setRetry(v => v + 1)}>{t('agent.retry')}</Button></div>}
    <ModelUsageStatistics statistics={usage?.statistics} days={days} onDaysChange={setDays} selectedDay={selectedDay || usage?.day} today={usage?.day} onDayChange={setSelectedDay} loading={loading} disabled={disabled} />
    <div className="agent-settings-field"><label htmlFor="agent-proxy-limit">{t('agent.proxy.dailyLimit')}</label><Input id="agent-proxy-limit" type="number" min="0.000001" max={1000000} step="0.000001" value={value.dailyLimit} onChange={event => onChange({ ...value, dailyLimit: event.target.value })} placeholder={t('agent.proxy.unlimited')} disabled={disabled} /></div>
    <div className="agent-settings-field"><label htmlFor="agent-proxy-currency">{t('agent.proxy.currency')}</label><Select id="agent-proxy-currency" aria-label={t('agent.proxy.currency')} value={value.currency} disabled={disabled} virtual={false} options={Array.from(new Set(['USD', 'CNY', 'EUR', 'GBP', 'JPY', value.currency, ...(usage?.charges.map(charge => charge.currency) || [])])).sort().map(currency => ({ value: currency, label: currency }))} onChange={currency => onChange({ ...value, currency })} /></div>
    <p className="agent-settings-hint">{t('agent.proxy.limitHint')}</p>
  </fieldset>
}
