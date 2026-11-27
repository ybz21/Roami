import { useEffect, useState } from 'react'
import { Alert, Button, Popconfirm, Radio, Select, message } from 'antd'
import { api } from '../../api'
import { type AgentKind } from '../../agent-kind'
import type { AgentModelView } from '../../agent-registry'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { selectableGatewayModels } from './gateway-model-catalog'
import { catalogFailure, gatewayModelName, useModelCatalog } from './model-hub-api'
import { getHashParams } from '../../route-hash'
import './model-hub.css'

const gatewayDefault = 'roami-default'
const endpoint = (value: string) => value.replace(/\/+$/, '').replace(/\/v1$/, '')

export default function GatewayModelBinding({ kind, view, onChanged, onModelLabel, installed = true }: { kind: AgentKind; view: AgentModelView; onChanged: () => Promise<void>; onModelLabel?: (label: string) => void; installed?: boolean }) {
  const { t } = useI18n(), catalog = useModelCatalog(), { phone } = useLayout()
  const [mode, setMode] = useState<'official' | 'custom' | null>(null)
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const models = catalog.value?.models || []
  const profile = view.profiles.find(profile => profile.applied || profile.id === view.activeId) || view.profiles.find(profile => endpoint(profile.baseUrl) === endpoint(view.current.baseUrl || ''))
  const throughGateway = !!profile && !!catalog.value?.baseUrl && endpoint(profile.baseUrl) === endpoint(catalog.value.baseUrl)
  const currentID = kind === 'claude' ? view.current.model?.replace(/^roami-claude\//, '').replace(/\[1m\]$/, '') : view.current.model
  const usesDefault = throughGateway && currentID === gatewayDefault
  const currentModel = throughGateway
    ? models.find(model => model.id === currentID || !!currentID && (model.gatewayAlias === currentID || catalog.value?.qualifiedModelIds?.[model.id] === currentID || model.aliases?.includes(currentID)))
    : models.find(model => {
      const candidate = model.candidates[0]
      if (!profile || model.aggregate || !candidate || candidate.model !== view.current.model) return false
      const source = catalog.value?.sources.find(source => source.id === candidate.sourceId)
      return source && source.protocol === profile.protocol && endpoint(source.baseUrl) === endpoint(profile.baseUrl)
    })
  const currentMode = view.mode || (profile || view.current.provider && view.current.provider !== 'openai' ? 'custom' : 'official')
  const selectedMode = mode || currentMode
  const available = selectableGatewayModels(catalog.value)
  const hasDefault = available.some(model => model.id === catalog.value?.defaultModel)
  const options = available.map(model => ({ value: model.id, label: model.name, title: model.name, callId: gatewayModelName(model, catalog.value) }))
  if (hasDefault) options.unshift({ value: gatewayDefault, label: t('hub.gatewayDefault'), title: t('hub.gatewayDefault'), callId: gatewayDefault })
  const currentSelection = usesDefault ? gatewayDefault : currentModel?.id
  const choice = model || currentSelection || (!throughGateway && hasDefault ? gatewayDefault : undefined)
  const selected = options.find(option => option.value === choice)?.value
  const currentLabel = usesDefault ? t('hub.gatewayDefault') : currentModel?.name || view.current.model || t('agent.models.notConfigured')
  const gatewayApplied = throughGateway && !!profile?.applied && !view.changed
  const expectedModels = [...(catalog.value?.defaultModel ? [{ id: gatewayDefault, name: 'Roami Default' }] : []), ...models.filter(model => !model.gatewayHidden && (!model.aggregate || model.enabled !== false)).map(model => ({ id: gatewayModelName(model, catalog.value), name: model.name }))]
  const catalogCurrent = kind !== 'pi' && kind !== 'opencode' || !!profile?.models && JSON.stringify(profile.models) === JSON.stringify(expectedModels)
  const applied = !view.changed && selectedMode === currentMode && (selectedMode === 'official' || gatewayApplied && catalogCurrent && !!selected && selected === currentSelection)
  const valid = installed && (selectedMode === 'official' || !!selected && !!catalog.value && !catalog.error)
  useEffect(() => { onModelLabel?.(usesDefault ? t('hub.gatewayDefault') : currentModel?.name || '') }, [usesDefault, currentModel?.name, onModelLabel, t])
  const apply = async () => {
    if (!valid || busy || applied) return
    setBusy(true); setError('')
    try {
      if (selectedMode === 'official') await api('POST', `/agent/professional/${kind}/models/default`, { revision: view.revision })
      else await api('POST', '/agent/model-gateway/catalog/apply', { kind, model: selected, revision: view.revision, catalogRevision: catalog.value!.revision })
      await onChanged(); setMode(null); catalog.retry(); message.success(t('capabilities.models.appliedMessage'))
      window.dispatchEvent(new Event('roam:agent-models-changed'))
    } catch (cause) { setError(catalogFailure(cause)) } finally { setBusy(false) }
  }
  const params = getHashParams().toString()
  return <section className="tt-model-binding">
    <p className="tt-model-binding-current">{t('hub.currentMode')}<strong>{currentMode === 'official' ? t('hub.mode.official') : gatewayApplied ? t('hub.gatewayCurrent', { model: currentLabel }) : currentLabel}</strong></p>
    {currentMode === 'custom' && profile?.applied && !view.changed && !throughGateway && <p role="status">{t('hub.directConnection')}</p>}
    <Radio.Group className="tt-model-binding-mode" aria-label={t('hub.connectionMode')} value={selectedMode} optionType="button" onChange={event => setMode(event.target.value)} disabled={busy} options={['official', 'custom'].map(value => ({ value, label: t('hub.mode.' + value) }))} />
    {!installed && <p>{t('hub.installFirst')}</p>}
    {(error || selectedMode === 'custom' && catalog.error) && <Alert type="error" message={t(error || catalog.error)} action={<Button onClick={() => { setError(''); catalog.retry(); void onChanged() }}>{t('capabilities.models.reread')}</Button>} />}
    {selectedMode === 'official' ? <p>{t('hub.factoryHint')}</p> : <>
      <div className="tt-model-binding-field">
        <label htmlFor={'agent-model-' + kind}>{t('modelUsage.model')}</label>
        <Select id={'agent-model-' + kind} virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }}
          aria-label={t('modelUsage.model')} placeholder={t('hub.chooseModel')} value={selected} options={options}
          placement={phone ? 'topLeft' : 'bottomLeft'} showSearch onChange={setModel}
          filterOption={(input, option) => [option?.label, option?.callId, option?.value].some(text => text?.toLowerCase().includes(input.trim().toLowerCase()))}
          loading={!catalog.value && !catalog.error} disabled={busy || !installed || !!catalog.error || !options.length} />
      </div>
      {catalog.value && !catalog.error && !options.length && <p role="status">{t('gatewayWorkspace.noCallable')}</p>}
      {selected === gatewayDefault && <p>{t('hub.gatewayDefaultHint')}</p>}
      {throughGateway && !catalogCurrent && <p role="status">{t('hub.gatewayCatalogChanged')}</p>}
      <details><summary>{t('hub.compatibility')}</summary><p>{t('hub.continuationHint')}</p></details>
    </>}
    <div className="tt-model-binding-actions"><Popconfirm classNames={{ root: 'tt-agent-install-confirm' }} title={t(selectedMode === 'official' ? 'hub.factoryConfirm' : 'capabilities.models.applyConfirm')} description={t(selectedMode === 'official' ? 'hub.factoryScope' : 'hub.applyScope')} onConfirm={apply} okText={t('capabilities.models.apply')} cancelText={t('common.cancel')}><Button type="primary" loading={busy} disabled={!valid || applied || busy}>{t(applied ? 'capabilities.models.applied' : 'capabilities.models.apply')}</Button></Popconfirm>
      {selectedMode === 'custom' && <Button href={'#/capabilities/models/catalog' + (params ? '?' + params : '')}>{t('hub.manageSources')}</Button>}
    </div>
  </section>
}
