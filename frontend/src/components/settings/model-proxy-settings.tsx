import { useEffect, useRef, useState } from 'react'
import { Button, Input, Select, Spin } from 'antd'
import { getHashParams } from '../../route-hash'
import { gatewayAgentNames } from '../capabilities/gateway-agent'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { ModelCharges, type ModelCharge } from './model-charges'
import { ModelUsageStatistics, type UsageStatistics } from './model-usage-statistics'
import { gatewayUsage, gatewayAgentTotals, type GatewayUsage, type UsageSource } from './local-model-gateway'

export type ModelPrice = { currency: string; input: number; output: number; cacheRead: number | null }
export type ModelProxyConfig = { dailyLimit: number | null; currency: string; prices?: Record<string, ModelPrice> }
export type PriceDraft = { currency: string; input: string; output: string; cacheRead: string }
export type ModelProxyDraft = { dailyLimit: string; currency: string; prices: Record<string, PriceDraft> }
export type ProxyUsage = { detailRetentionHours?: number; statistics?: UsageStatistics; day: string; timezone: string; requests: number; charges: ModelCharge[]; localCharges?: ModelCharge[]; estimatedCharges: ModelCharge[]; unknown: number; pending: number; missingUsage?: number; inputTokens: number; outputTokens: number; cacheReadTokens: number; recent: { inputTokens?: number | null; outputTokens?: number | null; cacheReadTokens?: number | null; requestId?: string; upstreamRequestId?: string; httpStatus?: number; upstreamHttpStatus?: number; sessionId?: string; sourceId?: string; routeId?: string; priceStatus?: string; agentKind?: string; id: string; role: string; source?: UsageSource; model: string; started_ms: number; state: string; cost_source: string; charges: ModelCharge[]; localCharges?: ModelCharge[]; estimatedCharges: ModelCharge[]; currency?: string; errorCode?: string; reconciliation?: string }[] }
export const proxyDraft = (config?: ModelProxyConfig): ModelProxyDraft => ({ dailyLimit: config?.dailyLimit?.toString() || '', currency: config?.currency || (config ? 'CNY' : 'USD'), prices: Object.fromEntries(Object.entries(config?.prices || {}).map(([model, price]) => [model, { currency: price.currency || config?.currency || 'CNY', input: String(price.input), output: String(price.output), cacheRead: price.cacheRead?.toString() ?? '' }])) })
export const priceFields = ['input', 'output', 'cacheRead'] as const
export const hasPrice = (price: PriceDraft) => priceFields.some(key => price[key] !== '')
export const proxyConfig = (draft: ModelProxyDraft): ModelProxyConfig => ({ dailyLimit: draft.dailyLimit === '' ? null : Number(draft.dailyLimit), currency: draft.currency, prices: Object.fromEntries(Object.entries(draft.prices).filter(([, price]) => hasPrice(price)).map(([model, price]) => [model, { currency: price.currency, input: Number(price.input), output: Number(price.output), cacheRead: price.cacheRead === '' ? null : Number(price.cacheRead) }])) })
const validAmount = (text: string) => { const value = Number(text); return text.trim() !== '' && Number.isFinite(value) && value >= 0 && value <= 1000000 }
export const validPriceDraft = (price: PriceDraft) => !hasPrice(price) || /^[A-Z]{3}$/.test(price.currency) && validAmount(price.input) && validAmount(price.output) && (price.cacheRead === '' || validAmount(price.cacheRead))
export const validProxyDraft = (draft: ModelProxyDraft) => (draft.dailyLimit === '' || validAmount(draft.dailyLimit) && Number(draft.dailyLimit) > 0) && /^[A-Z]{3}$/.test(draft.currency) && Object.values(draft.prices).filter(hasPrice).length <= 32 && Object.values(draft.prices).every(validPriceDraft)

export function ModelProxySettings({ value, disabled, onChange, snapshot, active, onReconcile }: { active: boolean; value: ModelProxyDraft; disabled: boolean; onChange: (value: ModelProxyDraft) => void; snapshot: unknown; onReconcile: (call: ProxyUsage['recent'][number]) => void }) {
  const { t, locale } = useI18n()
  const recentRef = useRef<HTMLElement>(null)
  const [recentState, setRecentState] = useState<'' | 'unknown'>('')
  const [selectedDay, setSelectedDay] = useState('')
  const [days, setDays] = useState(7), [loading, setLoading] = useState(false)
  const [source, setSource] = useState<UsageSource>('')
  const [agentKind, setAgentKind] = useState(() => { const kind = getHashParams().get('agentKind') || ''; return gatewayAgentNames[kind] ? kind : '' })
  const [result, setResult] = useState<{ usage: ProxyUsage; source: UsageSource; agentKind: string; recentState: string; agents: ReturnType<typeof gatewayAgentTotals> } | null>(null)
  const sourceMatches = result?.source === source && result?.agentKind === agentKind, usage = sourceMatches ? result?.usage : undefined
  const recentMatches = sourceMatches && result?.recentState === recentState
  const showUnknownCalls = () => { setRecentState('unknown'); recentRef.current?.scrollIntoView?.({ block: 'start' }) }
  const [failed, setFailed] = useState(false), [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!active) return
    const abort = new AbortController()
    setFailed(false); setLoading(true)
    const path = `/agent/model-gateway/usage?days=${days}${days === 1 && selectedDay ? '&day=' + encodeURIComponent(selectedDay) : ''}${source ? '&source=' + source : ''}${agentKind ? '&agentKind=' + agentKind : ''}${recentState ? '&recentState=' + recentState : ''}`
    void api('GET', path, undefined, { signal: abort.signal }).then(({ data }: { data: GatewayUsage }) => { if ((data.source || '') !== source || (data.agentKind || '') !== agentKind || (data.recentState || '') !== recentState) throw new Error('MODEL_USAGE_SOURCE_MISMATCH'); if (!abort.signal.aborted) setResult({ usage: gatewayUsage(data, value.currency), source, agentKind, recentState, agents: gatewayAgentTotals(data) }) }).catch(() => { if (!abort.signal.aborted) setFailed(true) }).finally(() => { if (!abort.signal.aborted) setLoading(false) })
    return () => abort.abort()
  }, [active, snapshot, retry, days, selectedDay, source, agentKind, recentState])
  const count = (amount: number) => new Intl.NumberFormat(locale).format(amount)
  const tokenCount = (amount: number | null | undefined) => amount == null ? t('agent.gateway.tokenUnknown') : count(amount)
  const todayTokens = usage && ((usage.missingUsage || 0) + usage.pending > 0 ? usage.inputTokens + usage.outputTokens > 0 ? t('agent.usage.knownTokens', { count: count(usage.inputTokens + usage.outputTokens) }) : t('agent.gateway.tokenUnknown') : count(usage.inputTokens + usage.outputTokens))
  return <fieldset className="agent-model-proxy" disabled={disabled}>
    <p className="agent-settings-hint">{t('agent.proxy.scope')}</p>
    {usage && Array.isArray(usage.charges) ? <>
      <div className="agent-proxy-totals" role="status">
        <div><span>{t('agent.proxy.todayCost')}</span><strong><ModelCharges charges={usage.charges} localCharges={usage.localCharges} estimatedCharges={usage.estimatedCharges} incomplete={usage.unknown > 0 || usage.pending > 0} /></strong></div>
        <div><span>{t('agent.proxy.requests')}</span><strong>{count(usage.requests)}</strong></div>
        <div><span>{t('agent.proxy.tokens')}</span><strong>{todayTokens}</strong></div>
      </div>
      <p className="agent-settings-hint">{t('agent.proxy.period', { day: new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(usage.day + 'T00:00:00Z')), zone: usage.timezone })}</p>
      {usage.unknown > 0 && <div className="agent-proxy-warning" role="status"><p className="agent-settings-hint">{t('agent.proxy.unknown', { count: count(usage.unknown) })}</p><button type="button" className="tt-act" onClick={showUnknownCalls}>{t('agent.gateway.viewCalls')}</button></div>}
      {usage.pending > 0 && <p className="agent-settings-hint">{t('agent.proxy.pending', { count: count(usage.pending) })}</p>}

    </> : !failed && <Spin size="small" />}
    {failed && <div role="alert"><p>{t('agent.proxy.loadFailed')}</p><Button onClick={() => setRetry(v => v + 1)}>{t('agent.retry')}</Button></div>}
    <ModelUsageStatistics statistics={sourceMatches ? usage?.statistics : undefined} days={days} onDaysChange={setDays} selectedDay={selectedDay || usage?.day} today={usage?.day} onDayChange={setSelectedDay} loading={loading} disabled={disabled} filterHint={t('agent.usage.sourceHint')} summaryContent={sourceMatches && !agentKind && !!result?.agents.length && <section className="agent-gateway-breakdown" aria-label={t('hub.billing.byAgent')}>{result.agents.map(row => <article key={row.agentKind}>
      <div><button type="button" className="tt-act" onClick={() => setAgentKind(row.agentKind)}>{gatewayAgentNames[row.agentKind] || row.agentKind}</button><span>{t('hub.billing.requests', { count: count(row.requests) })}</span>{row.unknown > 0 && <span>{t('agent.usage.unknown', { count: count(row.unknown) })}</span>}</div>
      <ModelCharges charges={row.charges} estimatedCharges={[]} incomplete={row.unknown > 0 || row.pending > 0} />
    </article>)}</section>} sourceControl={<><Select aria-label={t('hub.billing.agent')} value={agentKind} disabled={disabled} virtual={false} options={[{ value: '', label: t('hub.billing.all') }, ...Object.entries(gatewayAgentNames).map(([value, label]) => ({ value, label }))]} onChange={setAgentKind} /><Select aria-label={t('agent.usage.source')} value={source} disabled={disabled} virtual={false} options={['', 'rsi', 'other'].map(value => ({ value, label: t('agent.usage.source.' + (value || 'all')) }))} onChange={setSource} /></>} />
    {sourceMatches && usage && <section ref={recentRef} className="agent-proxy-records" aria-label={t('agent.proxy.recent')}>
      <div className="agent-proxy-records-head"><h4>{t('agent.proxy.recent')}</h4><button type="button" className="tt-act" aria-pressed={recentState === 'unknown'} disabled={disabled} onClick={() => setRecentState(recentState ? '' : 'unknown')}>{t('agent.gateway.onlyUnknown')}</button></div>
      {!!usage.detailRetentionHours && <p className="agent-settings-hint">{t('agent.gateway.retention', { days: count(usage.detailRetentionHours / 24) })}</p>}
      {!recentMatches ? <Spin size="small" /> : usage.recent.length ? <ul className="agent-proxy-calls">{usage.recent.map(call => <li key={call.id}>
        <div><strong>{call.model}</strong><span>{gatewayAgentNames[call.agentKind || ''] || t(call.role.startsWith('rsi_codex_') ? 'agent.proxy.rsiCodex' : call.source === 'rsi' || call.role.startsWith('rsi_') ? 'agent.proxy.rsi' : ['main', 'worker', 'memory'].includes(call.role) ? 'agent.models.role.' + call.role : 'agent.gateway.otherRole')} · {new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: usage.timezone }).format(call.started_ms)}</span>
          <dl className="agent-proxy-call-tokens">{([['inputTokens', 'agent.usage.input'], ['outputTokens', 'agent.usage.output'], ['cacheReadTokens', 'agent.usage.cache']] as const).map(([key, label]) => <div key={key}><dt>{t(label)}</dt><dd>{tokenCount(call[key])}</dd></div>)}</dl>
          <details><summary>{t('agent.gateway.callDetails')}</summary><dl className="agent-proxy-call-details">
            <div><dt>{t('agent.gateway.callId')}</dt><dd><code>{call.id}</code></dd></div>
            <div><dt>{t('agent.gateway.httpStatus')}</dt><dd>{call.httpStatus ? count(call.httpStatus) : t('agent.gateway.noResponse')}</dd></div>
            {([['requestId', 'agent.gateway.requestId'], ['upstreamRequestId', 'agent.gateway.upstreamRequestId'], ['sessionId', 'agent.gateway.sessionId'], ['routeId', 'agent.gateway.routeId'], ['sourceId', 'agent.gateway.sourceId']] as const).map(([key, label]) => call[key] && <div key={key}><dt>{t(label)}</dt><dd><code>{call[key]}</code></dd></div>)}
          </dl>{call.errorCode && <code>{call.errorCode}</code>}{call.reconciliation && <p>{call.reconciliation}</p>}</details>
        </div><span>{t(call.priceStatus === 'unpriced' && call.state === 'unknown' ? 'hub.billing.unpriced' : 'agent.proxy.state.' + call.state)}</span><strong><ModelCharges charges={call.charges} estimatedCharges={call.estimatedCharges} /></strong>{call.state === 'unknown' && <button type="button" className="tt-act" disabled={disabled} onClick={() => onReconcile(call)}>{t('agent.gateway.reconcile')}</button>}
      </li>)}</ul> : <p className="agent-settings-hint">{t('agent.gateway.noCalls')}</p>}
    </section>}
    <div className="agent-settings-field"><label htmlFor="agent-proxy-limit">{t('agent.proxy.dailyLimit')}</label><Input id="agent-proxy-limit" type="number" min="0" max={1000000} step="any" value={value.dailyLimit} onChange={event => onChange({ ...value, dailyLimit: event.target.value })} placeholder={t('agent.proxy.unlimited')} disabled={disabled} /></div>
    <div className="agent-settings-field"><label htmlFor="agent-proxy-currency">{t('agent.proxy.currency')}</label><Select id="agent-proxy-currency" aria-label={t('agent.proxy.currency')} value={value.currency} disabled={disabled} virtual={false} options={Array.from(new Set(['USD', 'CNY', 'EUR', 'GBP', 'JPY', value.currency, ...(usage?.charges.map(charge => charge.currency) || [])])).sort().map(currency => ({ value: currency, label: currency }))} onChange={currency => onChange({ ...value, currency })} /></div>
    <p className="agent-settings-hint">{t('agent.proxy.limitHint')}</p>
  </fieldset>
}
