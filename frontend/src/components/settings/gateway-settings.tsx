import { useEffect, useRef, useState } from 'react'
import { App, Button, Input, Modal, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useSettingsDraft } from './settings-draft'
import { ModelProxySettings, priceFields, type ModelProxyDraft, type ProxyUsage } from './model-proxy-settings'
import { ModelPriceSettings } from './model-price-settings'
import { gatewayConfiguration, gatewayDraft, validGatewayDraft, type GatewayConfiguration, type GatewayDraft } from './local-model-gateway'

function failure(error: unknown, t: (key: string) => string) {
  const code = (error as { apiError?: { code?: string } })?.apiError?.code
  return t(code === 'MODEL_PROXY_CURRENCY_MISMATCH' ? 'agent.gateway.periodBusy' : code === 'INVALID_MODEL_PROXY_CONFIG' ? 'agent.gateway.invalid' : code === 'MODEL_GATEWAY_CALL_NOT_UNKNOWN' ? 'agent.gateway.alreadySettled' : 'agent.gateway.failed')
}

export function useGatewaySettings(enabled: boolean) {
  const { t } = useI18n(), { message } = App.useApp()
  const [saved, setSaved] = useState<GatewayConfiguration | null>(null), [draft, setDraft] = useState<GatewayDraft | null>(null)
  const [error, setError] = useState(''), [saving, setSaving] = useState(false), [version, setVersion] = useState(0), [usageVersion, setUsageVersion] = useState(0)
  const [models, setModels] = useState<string[] | null>(null), [loadingModels, setLoadingModels] = useState(false), [catalogError, setCatalogError] = useState('')
  const [call, setCall] = useState<ProxyUsage['recent'][number] | null>(null), [amount, setAmount] = useState(''), [reason, setReason] = useState(''), [reconciling, setReconciling] = useState(false), [reconcileError, setReconcileError] = useState('')
  const live = useRef(true), catalogRequest = useRef<AbortController | null>(null)
  useEffect(() => { live.current = true; return () => { live.current = false; catalogRequest.current?.abort() } }, [])
  useEffect(() => {
    if (!enabled || saved) return
    const abort = new AbortController()
    setError('')
    void api('GET', '/agent/model-gateway/settings', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) { setSaved(data); setDraft(gatewayDraft(data)) } }).catch(cause => { if (!abort.signal.aborted) setError(failure(cause, t)) })
    return () => abort.abort()
  }, [enabled, saved, version])
  const notice = useSettingsDraft('local-model-gateway', draft, saved ? gatewayDraft(saved) : null, setDraft, !!draft && !!saved)
  const dirty = !!draft && !!saved && JSON.stringify(gatewayConfiguration(draft)) !== JSON.stringify(gatewayConfiguration(gatewayDraft(saved)))
  const save = async () => {
    if (!draft || saving || !validGatewayDraft(draft)) return
    setSaving(true); setError('')
    try {
      const { data } = await api('PUT', '/agent/model-gateway/settings', gatewayConfiguration(draft))
      if (live.current) { setSaved(data); setDraft(gatewayDraft(data)); setUsageVersion(value => value + 1); message.success(t('agent.gateway.saved')) }
    } catch (cause) { if (live.current) setError(failure(cause, t)) }
    finally { if (live.current) setSaving(false) }
  }
  const catalog = async () => {
    if (loadingModels) return
    const abort = new AbortController(); catalogRequest.current = abort
    setLoadingModels(true); setCatalogError('')
    try { const { data } = await api('GET', '/agent/models?role=main', undefined, { signal: abort.signal }); if (!abort.signal.aborted) setModels(data.models) }
    catch (cause) { if (!abort.signal.aborted) setCatalogError(failure(cause, t)) }
    finally { if (!abort.signal.aborted) setLoadingModels(false) }
  }
  const reconcile = async () => {
    if (!call || reconciling || amount.trim() === '' || !Number.isFinite(Number(amount)) || Number(amount) < 0 || Number(amount) > 1_000_000 || !reason.trim()) return
    setReconciling(true); setReconcileError('')
    try {
      await api('PUT', '/agent/model-gateway/calls/' + encodeURIComponent(call.id), { amount: Number(amount), reason: reason.trim() })
      if (live.current) { setCall(null); setUsageVersion(value => value + 1); message.success(t('agent.gateway.reconciled')) }
    } catch (cause) { if (live.current) setReconcileError(failure(cause, t)) }
    finally { if (live.current) setReconciling(false) }
  }
  return { saved, draft, setDraft, error, saving, dirty, save, notice, usageVersion, models, loadingModels, catalogError, catalog,
    retry: () => setVersion(value => value + 1), discard: () => { if (saved) { setDraft(gatewayDraft(saved)); setError('') } },
    call, amount, setAmount, reason, setReason, reconciling, reconcileError, reconcile,
    openReconcile: (value: ProxyUsage['recent'][number]) => { setCall(value); setAmount(''); setReason(''); setReconcileError('') }, closeReconcile: () => { if (!reconciling) setCall(null) } }
}
type Controller = ReturnType<typeof useGatewaySettings>

export function GatewaySettingsForm({ controller: c, mode, active, models }: { controller: Controller; mode: 'proxy' | 'prices'; active: boolean; models: string[] }) {
  const { t } = useI18n()
  if (!c.draft) return c.error ? <div role="alert"><p>{c.error}</p><Button onClick={c.retry}>{t('agent.retry')}</Button></div> : <Spin />
  const draft = c.draft
  const update = (value: ModelProxyDraft) => c.setDraft(previous => previous ? { ...previous, ...value } : previous)
  return <form className="agent-settings-form" onSubmit={event => { event.preventDefault(); void c.save() }}>
    {c.notice}
    {mode === 'proxy' ? <>
      <ModelProxySettings value={draft} disabled={c.saving} onChange={update} snapshot={c.usageVersion} active={active} onReconcile={c.openReconcile} />
      <div className="agent-settings-field"><label htmlFor="agent-gateway-timezone">{t('agent.gateway.timezone')}</label><Input id="agent-gateway-timezone" value={draft.timezone} disabled={c.saving} maxLength={100} onChange={event => c.setDraft({ ...draft, timezone: event.target.value })} /></div>
      <p className="agent-settings-hint">{t('agent.gateway.periodHint')}</p>
    </> : <>
      <p className="agent-settings-hint">{t('agent.gateway.priceCurrency', { currency: draft.currency })}</p>
      <fieldset><legend>{t('agent.gateway.defaultPrice')}</legend><p className="agent-settings-hint">{t('hub.keys.priceHint')}</p><div className="agent-proxy-price-fields">{priceFields.map(key => <div className="agent-settings-field" key={key}><label htmlFor={`agent-default-price-${key}`}>{t('agent.proxy.price.' + key)}</label><Input id={`agent-default-price-${key}`} type="number" min={0} max={1_000_000} step="any" disabled={c.saving} value={draft.defaultPrice[key]} onChange={event => c.setDraft({ ...draft, defaultPrice: { ...draft.defaultPrice, [key]: event.target.value } })} /></div>)}</div></fieldset>
      <ModelPriceSettings value={draft} models={models} catalog={c.models} loadingCatalog={c.loadingModels} catalogError={c.catalogError} loadCatalog={() => { void c.catalog() }} disabled={c.saving} onChange={update} />
    </>}
    {c.error && <p className="agent-settings-error" role="alert">{c.error}</p>}
    {!validGatewayDraft(draft) && <p className="agent-settings-error" role="status">{t('agent.gateway.invalid')}</p>}
    <div className="agent-settings-save"><span role="status">{t(c.dirty ? 'agent.models.unsaved' : 'agent.models.savedState')}</span><Button disabled={!c.dirty || c.saving} onClick={c.discard}>{t('agent.models.discard')}</Button><Button type="primary" htmlType="submit" loading={c.saving} disabled={!c.dirty || !validGatewayDraft(draft)}>{t('agent.models.save')}</Button></div>
  </form>
}

export function GatewayReconciliation({ controller: c }: { controller: Controller }) {
  const { t } = useI18n()
  const valid = c.amount.trim() !== '' && Number.isFinite(Number(c.amount)) && Number(c.amount) >= 0 && Number(c.amount) <= 1_000_000 && !!c.reason.trim()
  return <Modal className="agent-gateway-reconcile" open={!!c.call} title={t('agent.gateway.reconcile')} onCancel={c.closeReconcile} onOk={() => { void c.reconcile() }} confirmLoading={c.reconciling} okText={t('agent.gateway.confirmReconcile')} cancelText={t('common.cancel')} okButtonProps={{ disabled: !valid }} cancelButtonProps={{ disabled: c.reconciling }} closable={!c.reconciling} maskClosable={!c.reconciling}>
    <div className="agent-settings-tab"><p>{c.call?.model}</p><p className="agent-settings-hint">{t('agent.gateway.reconcileHint')}</p>
      <div className="agent-settings-field"><label htmlFor="agent-gateway-amount">{t('agent.gateway.amount', { currency: c.call?.currency || '' })}</label><Input id="agent-gateway-amount" type="number" min={0} max={1_000_000} step="any" value={c.amount} disabled={c.reconciling} onChange={event => c.setAmount(event.target.value)} /></div>
      <div className="agent-settings-field"><label htmlFor="agent-gateway-reason">{t('agent.gateway.reason')}</label><Input.TextArea id="agent-gateway-reason" value={c.reason} maxLength={500} disabled={c.reconciling} onChange={event => c.setReason(event.target.value)} /></div>
      {c.reconcileError && <p className="agent-settings-error" role="alert">{c.reconcileError}</p>}
    </div>
  </Modal>
}
