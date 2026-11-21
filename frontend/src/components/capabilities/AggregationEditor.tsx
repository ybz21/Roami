import { useEffect, useId, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, InputNumber, Select, TabBar, Popconfirm } from './model-controls'
import { useI18n } from '../../i18n'
import { ChevronRight } from '../../icons'
import type { CatalogModel, ModelCatalog } from './model-hub-api'
import { routingStrategies, type RoutingStrategy } from './model-routing-api'
import { MAX_AGGREGATE_MEMBERS } from './routing-preview'
import AggregationMemberPicker from './AggregationMemberPicker'
import RoutingStrategyPreview from './RoutingStrategyPreview'
import AggregationRuntime from './AggregationRuntime'
import AggregationMonitor from './AggregationMonitor'
import { useModelMemberFacts } from './model-member-facts'

export type AggregationSection = 'members' | 'routing' | 'monitor'

export default function AggregationEditor({ model, original, catalog, active, busy, valid, error, section, onSection, onChange, onSave, onCancel, onDelete, onSource, onRequest, retry }: {
  model: CatalogModel; original: string | null; catalog: ModelCatalog; active: boolean; busy: boolean; valid: boolean; error: string
  section?: AggregationSection; onSection: (section: AggregationSection) => void
  onChange: (patch: Partial<CatalogModel>) => void; onSave: () => void; onCancel: () => void; onDelete: () => Promise<boolean>; onSource: (source: string) => void; onRequest: (id: string) => void; retry: () => void
}) {
  const { t, locale } = useI18n(), [creationTab, setCreationTab] = useState<AggregationSection>('members'), scroll = useRef<HTMLDivElement>(null)
  const tab = section ?? creationTab
  const setTab = section === undefined ? setCreationTab : onSection
  const more = useRef<HTMLDetailsElement>(null)
  const fieldId = useId(), [attempted, setAttempted] = useState(false), [touched, setTouched] = useState<Record<string, boolean>>({})
  const nameError = !model.name.trim() ? t('orchestration.nameRequired') : ''
  const idError = model.id === 'roami-default' || !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$/.test(model.id) ? t('orchestration.idInvalid') : catalog.models.some(row => row.id !== original && (row.id === model.id || row.aliases?.includes(model.id))) ? t('orchestration.idTaken') : ''
  const saved = catalog.models.find(row => row.id === original)
  const { facts, status } = useModelMemberFacts(model, saved, catalog, active && tab === 'routing')
  useEffect(() => { if (scroll.current) scroll.current.scrollTop = 0 }, [tab])
  useEffect(() => { if (attempted && !valid && tab !== 'monitor') scroll.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus() }, [attempted, tab])
  const tabs: AggregationSection[] = saved ? ['members', 'routing', 'monitor'] : ['members', 'routing']
  return <div className="tt-aggregate-editor">
    <TabBar className="tt-aggregate-tabs" activeKey={tab} onChange={key => setTab(key as AggregationSection)} items={tabs.map(key => ({ key, label: t('pool.section.' + key) }))} />
    <form className="tt-aggregate-editor" hidden={tab === 'monitor'} onSubmit={event => { event.preventDefault(); if (valid) onSave(); else { setAttempted(true); if (idError && more.current) more.current.open = true; const next = nameError || idError || !model.candidates.length ? 'members' : 'routing'; if (next !== tab) setTab(next) } }}>
    <div className={"tt-routing-editor tt-aggregate-editor-content" + (tab === 'members' ? ' is-members' : '')} ref={scroll}>
      {error && <Alert role="alert" type="error" message={t(error)} action={<Button onClick={retry}>{t('agent.retry')}</Button>} />}
      <section hidden={tab !== 'members'} aria-label={t('pool.section.members')}>
        <div className="tt-aggregate-basics">
          <label className="agent-settings-field tt-aggregate-identity">{t('pool.name')}<Input id={fieldId + '-name'} aria-describedby={fieldId + '-name-error'} aria-invalid={!!nameError && (attempted || touched.name)} aria-label={t('pool.name')} onBlur={() => setTouched(value => ({ ...value, name: true }))} value={model.name} disabled={busy} maxLength={100} onChange={event => onChange({ name: event.target.value })} />{nameError && (attempted || touched.name) && <small className="tt-model-field-error" id={fieldId + '-name-error'} role="alert">{nameError}</small>}</label>
        </div>
        {attempted && !model.candidates.length && <p className="tt-model-field-error" role="alert">{t('orchestration.membersRequired')}</p>}
        <AggregationMemberPicker model={model} original={original} catalog={catalog} active={active && tab === 'members'} disabled={busy} onChange={onChange} onSource={onSource} />
        <details className="tt-aggregate-more" ref={more}>
          <summary><ChevronRight />{t('orchestration.moreSettings')}{model.enabled === false && <small>{t('pool.disabled')}</small>}</summary>
          <div className="tt-aggregate-settings"><label className="agent-settings-field">{t('pool.modelId')}<Input id={fieldId + '-id'} aria-describedby={fieldId + '-id-error'} aria-invalid={!!idError && (attempted || touched.id)} aria-label={t('pool.modelId')} onBlur={() => setTouched(value => ({ ...value, id: true }))} value={model.id} disabled={busy} maxLength={160} onChange={event => onChange({ id: event.target.value })} />{idError && (attempted || touched.id) && <small className="tt-model-field-error" id={fieldId + '-id-error'} role="alert">{idError}</small>}</label>
          <p className="agent-settings-hint">{t(original ? 'pool.renameHint' : 'orchestration.autoId')}</p>
          <div className="tt-model-source-management"><Checkbox disabled={busy} checked={model.enabled !== false} onChange={event => onChange({ enabled: event.target.checked })}>{t('pool.enabled')}</Checkbox>{saved && <Popconfirm title={t('pool.delete')} onConfirm={onDelete}><button type="button" className="tt-act danger" disabled={busy || !!catalog.uses[saved.id]?.length}>{t('capabilities.models.deleteAction')}</button></Popconfirm>}</div></div>
        </details>
      </section>
      <section hidden={tab !== 'routing'} aria-label={t('pool.section.routing')}>
        {saved && <AggregationRuntime model={saved} catalog={catalog} status={status} onRequest={onRequest} hasDraft={JSON.stringify(saved) !== JSON.stringify(model)} />}
        <RoutingStrategyPreview model={model} sources={catalog.sources} pools={catalog.models.filter(row => row.aggregate)} onChange={onChange} disabled={busy || !active || tab !== 'routing'} facts={facts} configuration={<>
          <label className="agent-settings-field"><span>{t('pool.strategy')}</span><Select aria-label={t('pool.strategy')} virtual={false} disabled={busy} value={model.strategy} options={routingStrategies.map(value => ({ value, label: t('pool.strategy.' + value) }))} onChange={(strategy: RoutingStrategy) => onChange({ strategy })} /></label>
          <p className="agent-settings-hint">{t('pool.strategy.' + model.strategy + '.summary')}</p>
          <details className="tt-routing-guide"><summary><ChevronRight />{t('pool.policyDetails')}</summary><p>{t('pool.strategy.' + model.strategy + '.detail')}</p>{model.strategy === 'cheap' && <p>{t('pool.timePriceHint')}</p>}</details>
        </>} />
        <details className="tt-aggregate-options"><summary><ChevronRight />{t('pool.requestOptions')}</summary>
          <div className="tt-routing-flags"><Checkbox disabled={busy} checked={model.requireTools} onChange={event => onChange({ requireTools: event.target.checked })}>{t('pool.requireTools')}</Checkbox></div>
          <div className="tt-routing-fields"><label className="agent-settings-field">{t('pool.context')}<InputNumber aria-label={t('pool.context')} disabled={busy} min={0} max={10000000} step={1000} precision={0} value={model.minContext || 0} onChange={value => onChange({ minContext: value || 0 })} /></label><label className="agent-settings-field">{t('pool.cooldown')}<Select aria-label={t('pool.cooldown')} disabled={busy} value={model.cooldownSeconds || 60} options={[30, 60, 120, 300].map(value => ({ value, label: t('pool.seconds', { count: value }) }))} onChange={cooldownSeconds => onChange({ cooldownSeconds })} /></label></div>
          <div className="tt-routing-flags"><Checkbox disabled={busy} checked={model.onLimit !== false} onChange={event => onChange({ onLimit: event.target.checked })}>{t('pool.onLimit')}</Checkbox><Checkbox disabled={busy} checked={model.onExhausted !== false} onChange={event => onChange({ onExhausted: event.target.checked })}>{t('pool.onExhausted')}</Checkbox><p className="agent-settings-hint">{t('pool.noReplay')}</p></div>
        </details>
      </section>
    </div>
    <footer className="tt-model-source-footer tt-aggregate-footer"><span role="status">{t('pool.memberSummary', { count: new Intl.NumberFormat(locale).format(model.candidates.length), max: MAX_AGGREGATE_MEMBERS })}{attempted && !valid && !nameError && !idError && !!model.candidates.length && <small role="alert">{t('pool.invalid')}</small>}</span><div><Button onClick={onCancel} disabled={busy}>{t('common.cancel')}</Button><Button type="primary" htmlType="submit" disabled={busy} loading={busy}>{t('agent.models.save')}</Button></div></footer>
    </form>
    {saved && <AggregationMonitor poolId={saved.id} visible={tab === 'monitor'} active={active} />}
  </div>
}
