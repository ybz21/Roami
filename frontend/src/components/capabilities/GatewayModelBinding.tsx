import { useEffect, useState } from 'react'
import { Alert, Button, Popconfirm, Radio, Select, message } from 'antd'
import { api } from '../../api'
import { type AgentKind } from '../../agent-kind'
import { type AgentModelView } from '../../agent-registry'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { catalogFailure, useModelCatalog } from './model-hub-api'
import { getHashParams } from '../../route-hash'
import './model-hub.css'

const discoveredPrefix = 'source-model:'
const endpoint = (value: string) => value.replace(/\/+$/, '').replace(/\/v1$/, '')
export default function GatewayModelBinding({ kind, view, onChanged, onModelLabel, installed = true }: { kind: AgentKind; view: AgentModelView; onChanged: () => Promise<void>; onModelLabel?: (label: string) => void; installed?: boolean }) {
  const { t } = useI18n(), catalog = useModelCatalog(), { phone } = useLayout()
  const [mode, setMode] = useState<'official' | 'custom' | null>(null), [source, setSource] = useState(''), [model, setModel] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [directory, setDirectory] = useState<{ key: string; models: string[]; loading: boolean; error: string }>({ key: '', models: [], loading: false, error: '' }), [directoryVersion, setDirectoryVersion] = useState(0), [search, setSearch] = useState('')
  const compatible = (protocol: string) => kind === 'codex' ? protocol === 'openai-responses' : kind === 'claude' ? protocol === 'anthropic-messages' : true
  const sources = (catalog.value?.sources || []).filter(source => compatible(source.protocol))
  const models = (catalog.value?.models || []).filter(model => compatible(model.protocol))
  const profile = view.profiles.find(profile => profile.applied || profile.id === view.activeId)
  const currentModel = models.find(model => model.id === view.current.model) || models.find(model => {
    const source = sources.find(source => source.id === model.candidates[0].sourceId)
    return profile && source && endpoint(source.baseUrl) === endpoint(profile.baseUrl) && model.candidates[0].model === view.current.model
  })
  const currentMode = view.mode || (profile || view.current.provider && view.current.provider !== 'openai' ? 'custom' : 'official')
  const selectedMode = mode || currentMode
  const selectedSource = source || currentModel?.candidates[0].sourceId
  const directoryKey = selectedSource + ':' + catalog.value?.revision
  const remote = directory.key === directoryKey ? directory : { models: [], loading: false, error: '' }
  useEffect(() => {
    if (selectedMode !== 'custom' || !selectedSource || !catalog.value?.revision || !installed) return
    const abort = new AbortController()
    const key = selectedSource + ':' + catalog.value.revision
    setDirectory({ key, models: [], loading: true, error: '' })
    void api('POST', '/agent/model-gateway/catalog/source-models', { kind, sourceId: selectedSource, revision: catalog.value.revision }, { signal: abort.signal }).then(({ data }) => {
      if (!abort.signal.aborted) setDirectory({ key, models: Array.isArray(data?.models) ? data.models.filter((model: unknown): model is string => typeof model === 'string' && !!model && model.length <= 200) : [], loading: false, error: '' })
    }).catch(cause => {
      if (!abort.signal.aborted) setDirectory({ key, models: [], loading: false, error: cause?.apiError?.code === 'MODEL_CATALOG_CHANGED' ? 'hub.error.changed' : cause?.apiError?.code === 'MODEL_LIST_UNSUPPORTED' ? 'hub.sourceListUnsupported' : 'hub.sourceListFailed' })
    })
    return () => abort.abort()
  }, [kind, selectedMode, selectedSource, catalog.value?.revision, installed, directoryVersion])
  const options = models.filter(model => model.candidates[0].sourceId === selectedSource).map(model => ({ value: model.id, label: model.name, title: model.candidates[0].model, upstreamModel: model.candidates[0].model, configured: true }))
  const pendingModel = model.startsWith(discoveredPrefix) ? decodeURIComponent(model.slice(discoveredPrefix.length)) : ''
  const query = search.trim()
  for (const id of new Set([...remote.models, ...(pendingModel ? [pendingModel] : []), ...(query && query.length <= 200 ? [query] : [])])) {
    if (!options.some(option => option.upstreamModel === id)) options.push({ value: discoveredPrefix + encodeURIComponent(id), label: id, title: id, upstreamModel: id, configured: false })
  }
  const selectedOption = options.find(option => option.value === model) || (pendingModel ? options.find(option => option.upstreamModel === pendingModel) : undefined) || (selectedSource === currentModel?.candidates[0].sourceId ? options.find(option => option.value === currentModel?.id) : undefined)
  const selected = selectedOption?.value
  const currentLabel = currentModel?.name || (view.current.provider === 'Roami Gateway' ? t('hub.mode.custom') : view.current.model || t('hub.mode.custom'))
  const applied = !view.changed && selectedMode === currentMode && (selectedMode === 'official' || !!selected && selected === currentModel?.id && !!profile?.applied)
  const valid = installed && (selectedMode === 'official' || !!selectedSource && !!selected && !!catalog.value)
  useEffect(() => { onModelLabel?.(currentModel?.name || '') }, [currentModel?.name, onModelLabel])
  const apply = async () => {
    if (!valid || busy || applied) return
    setBusy(true); setError('')
    try {
      if (selectedMode === 'official') await api('POST', `/agent/professional/${kind}/models/default`, { revision: view.revision })
      else await api('POST', '/agent/model-gateway/catalog/apply', { kind, sourceId: selectedSource, ...(selectedOption!.configured ? { model: selected } : { upstreamModel: selectedOption!.upstreamModel }), revision: view.revision, catalogRevision: catalog.value!.revision })
      await onChanged(); setMode(null); catalog.retry(); message.success(t('capabilities.models.appliedMessage'))
      window.dispatchEvent(new Event('roam:agent-models-changed'))
    } catch (cause) { setError(catalogFailure(cause)) } finally { setBusy(false) }
  }
  const params = getHashParams().toString()
  return <section className="tt-model-binding">
    <p className="tt-model-binding-current">{t('hub.currentMode')}<strong>{currentMode === 'official' ? t('hub.mode.official') : currentLabel}</strong></p>
    <Radio.Group className="tt-model-binding-mode" aria-label={t('hub.connectionMode')} value={selectedMode} optionType="button" onChange={event => setMode(event.target.value)} disabled={busy} options={['official', 'custom'].map(value => ({ value, label: t('hub.mode.' + value) }))} />
    {!installed && <p>{t('hub.installFirst')}</p>}
    {(error || selectedMode === 'custom' && catalog.error) && <Alert type="error" message={t(error || catalog.error)} action={<Button onClick={() => { catalog.retry(); void onChanged() }}>{t('capabilities.models.reread')}</Button>} />}
    {selectedMode === 'official' ? <p>{t('hub.factoryHint')}</p> : <>
      <div className="tt-model-binding-field"><label htmlFor={'agent-source-' + kind}>{t('hub.source')}</label><Select id={'agent-source-' + kind} virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('hub.source')} placeholder={t('hub.chooseSource')} value={selectedSource} options={sources.map(source => ({ value: source.id, label: source.name }))} onChange={source => { setSource(source); setModel(''); setSearch('') }} disabled={busy || !installed} loading={!catalog.value && !catalog.error} /></div>
      <div className="tt-model-binding-field"><label htmlFor={'agent-model-' + kind}>{t('hub.tab.catalog')}</label><Select id={'agent-model-' + kind} virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('hub.tab.catalog')} placeholder={t('hub.chooseModel')} value={selected} options={options} placement={phone ? 'topLeft' : 'bottomLeft'} showSearch loading={remote.loading} onSearch={setSearch} onChange={value => { setModel(value); setSearch('') }} filterOption={(input, option) => String(option?.label || '').toLowerCase().includes(input.toLowerCase()) || String(option?.upstreamModel || '').toLowerCase().includes(input.toLowerCase())} disabled={busy || !installed || !selectedSource} /></div>
      {remote.error && <div className="tt-model-binding-actions"><p role="status">{t(remote.error)}</p><Button onClick={() => { catalog.retry(); setDirectoryVersion(value => value + 1) }}>{t('agent.retry')}</Button></div>}
      {catalog.value && (!sources.length || selectedSource && !remote.loading && !remote.error && !options.length) && <p>{t(sources.length ? 'hub.sourceNoModels' : 'hub.noCompatibleSource')}</p>}
      <details><summary>{t('hub.compatibility')}</summary><p>{t('hub.continuationHint')}</p></details>
    </>}
    <div className="tt-model-binding-actions"><Popconfirm classNames={{ root: 'tt-agent-install-confirm' }} title={t(selectedMode === 'official' ? 'hub.factoryConfirm' : 'capabilities.models.applyConfirm')} description={t(selectedMode === 'official' ? 'hub.factoryScope' : 'hub.applyScope')} onConfirm={apply} okText={t('capabilities.models.apply')} cancelText={t('common.cancel')}><Button type="primary" loading={busy} disabled={!valid || applied || busy}>{t(applied ? 'capabilities.models.applied' : 'capabilities.models.apply')}</Button></Popconfirm>
      {selectedMode === 'custom' && <Button href={'#/capabilities/models/sources' + (params ? '?' + params : '')}>{t('hub.manageSources')}</Button>}
    </div>
  </section>
}
