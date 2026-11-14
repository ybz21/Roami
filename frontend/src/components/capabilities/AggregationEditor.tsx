import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, InputNumber, Select, Tabs, Popconfirm } from 'antd'
import { useI18n } from '../../i18n'
import type { CatalogModel, ModelCatalog } from './model-hub-api'
import { routingStrategies, type RoutingStrategy } from './model-routing-api'
import { MAX_AGGREGATE_MEMBERS } from './routing-preview'
import AggregationMemberPicker from './AggregationMemberPicker'
import RoutingStrategyPreview from './RoutingStrategyPreview'
import AggregationRuntime from './AggregationRuntime'

export default function AggregationEditor({ model, original, catalog, active, busy, valid, error, onChange, onSave, onCancel, onDelete, onSource, retry }: {
  model: CatalogModel; original: string | null; catalog: ModelCatalog; active: boolean; busy: boolean; valid: boolean; error: string
  onChange: (patch: Partial<CatalogModel>) => void; onSave: () => void; onCancel: () => void; onDelete: () => Promise<boolean>; onSource: (source: string) => void; retry: () => void
}) {
  const { t, locale } = useI18n(), [tab, setTab] = useState('members'), scroll = useRef<HTMLDivElement>(null)
  const saved = catalog.models.find(row => row.id === original)
  useEffect(() => { if (scroll.current) scroll.current.scrollTop = 0 }, [tab])
  return <form className="tt-aggregate-editor" onSubmit={event => { event.preventDefault(); onSave() }}>
    <Tabs className="tt-aggregate-tabs" activeKey={tab} onChange={setTab} items={[...['members', 'routing'].map(key => ({ key, label: t('pool.section.' + key) })), ...(saved ? [{ key: 'runtime', label: t('pool.runtime') }] : [])]} />
    <div className="tt-routing-editor tt-aggregate-editor-content" ref={scroll}>
      {error && <Alert role="alert" type="error" message={t(error)} action={<Button onClick={retry}>{t('agent.retry')}</Button>} />}
      <section hidden={tab !== 'members'} aria-label={t('pool.section.members')}>
        <div className="tt-routing-fields tt-aggregate-identity"><label className="agent-settings-field">{t('pool.name')}<Input aria-label={t('pool.name')} value={model.name} disabled={busy} maxLength={100} onChange={event => onChange({ name: event.target.value })} /></label><label className="agent-settings-field">{t('pool.modelId')}<Input aria-label={t('pool.modelId')} value={model.id} disabled={busy} maxLength={160} onChange={event => onChange({ id: event.target.value })} /></label></div>
        {original && <p className="agent-settings-hint">{t('pool.renameHint')}</p>}
        <AggregationMemberPicker model={model} original={original} catalog={catalog} active={active && tab === 'members'} disabled={busy} onChange={onChange} onSource={onSource} />
        <div className="tt-model-source-management"><Checkbox disabled={busy} checked={model.enabled !== false} onChange={event => onChange({ enabled: event.target.checked })}>{t('pool.enabled')}</Checkbox>{saved && <Popconfirm title={t('pool.delete')} onConfirm={onDelete}><button type="button" className="tt-act danger" disabled={busy || !!catalog.uses[saved.id]?.length}>{t('capabilities.models.deleteAction')}</button></Popconfirm>}</div>
      </section>
      <section hidden={tab !== 'routing'} aria-label={t('pool.section.routing')}>
        <label className="agent-settings-field tt-aggregate-strategy">{t('pool.strategy')}<Select aria-label={t('pool.strategy')} virtual={false} disabled={busy} value={model.strategy} options={routingStrategies.map(value => ({ value, label: t('pool.strategy.' + value) + ' · ' + value + (value === 'smart' ? ' · ' + t('pool.default') : '') }))} onChange={(strategy: RoutingStrategy) => onChange({ strategy })} /></label>
        <div className="tt-routing-guide"><p>{t('pool.strategy.' + model.strategy + '.summary')}</p><details><summary>{t('pool.policyDetails')}</summary><p>{t('pool.strategy.' + model.strategy + '.detail')}</p>{model.strategy === 'cheap' && <p>{t('pool.timePriceHint')}</p>}</details></div>
        <RoutingStrategyPreview model={model} sources={catalog.sources} pools={catalog.models.filter(row => row.aggregate)} onChange={onChange} disabled={busy || !active || tab !== 'routing'} />
        <details className="tt-aggregate-options"><summary>{t('pool.requestOptions')}</summary>
          <div className="tt-routing-flags"><Checkbox disabled={busy} checked={model.freeOnly === true} onChange={event => onChange({ freeOnly: event.target.checked })}>{t('pool.freeOnly')}</Checkbox>{model.freeOnly === true && <><Checkbox disabled={busy} checked={model.allowPlan} onChange={event => onChange({ allowPlan: event.target.checked })}>{t('pool.allowPlan')}</Checkbox><p className="agent-settings-hint">{t('pool.noPaid')}</p></>}{!model.freeOnly && <p className="agent-settings-hint">{t('pool.paidGroup')}</p>}<Checkbox disabled={busy} checked={model.requireTools} onChange={event => onChange({ requireTools: event.target.checked })}>{t('pool.requireTools')}</Checkbox></div>
          <div className="tt-routing-fields"><label className="agent-settings-field">{t('pool.context')}<InputNumber aria-label={t('pool.context')} disabled={busy} min={0} max={10000000} step={1000} precision={0} value={model.minContext || 0} onChange={value => onChange({ minContext: value || 0 })} /></label><label className="agent-settings-field">{t('pool.cooldown')}<Select aria-label={t('pool.cooldown')} disabled={busy} value={model.cooldownSeconds || 60} options={[30, 60, 120, 300].map(value => ({ value, label: t('pool.seconds', { count: value }) }))} onChange={cooldownSeconds => onChange({ cooldownSeconds })} /></label></div>
          <div className="tt-routing-flags"><Checkbox disabled={busy} checked={model.onLimit !== false} onChange={event => onChange({ onLimit: event.target.checked })}>{t('pool.onLimit')}</Checkbox><Checkbox disabled={busy} checked={model.onExhausted !== false} onChange={event => onChange({ onExhausted: event.target.checked })}>{t('pool.onExhausted')}</Checkbox><p className="agent-settings-hint">{t('pool.noReplay')}</p></div>
        </details>
      </section>
      {saved && tab === 'runtime' && <section aria-label={t('pool.runtime')}><p className="agent-settings-hint">{t('pool.savedRuntime')}</p><AggregationRuntime model={saved} sources={catalog.sources} revision={catalog.revision} active={active} /></section>}
    </div>
    <footer className="tt-model-source-footer tt-aggregate-footer"><span role="status">{t('pool.memberSummary', { count: new Intl.NumberFormat(locale).format(model.candidates.length), max: MAX_AGGREGATE_MEMBERS })}{!valid && <small>{t('pool.invalid')}</small>}</span><div><Button onClick={onCancel} disabled={busy}>{t('common.cancel')}</Button><Button type="primary" htmlType="submit" disabled={!valid} loading={busy}>{t('agent.models.save')}</Button></div></footer>
  </form>
}
