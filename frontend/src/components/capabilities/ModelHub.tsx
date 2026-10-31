import { useState } from 'react'
import { Alert, App, Button, Input, Popconfirm, Select, Spin, Tabs } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { getHashParams } from '../../route-hash'
import { PlusIcon, LinkIcon } from '../../icons'
import MobileSubPage from '../MobileSubPage'
import { GatewaySettingsForm, GatewayReconciliation, useGatewaySettings } from '../settings/gateway-settings'
import { useModelCatalog, modelProtocols, type ModelSource, type CatalogModel } from './model-hub-api'
import '../settings/agent-settings.css'
import './model-hub.css'

const tabs = ['catalog', 'usage', 'prices']
const newID = () => globalThis.crypto?.randomUUID?.() || Date.now().toString(36)
export default function ModelHub({ sub = '', onNav }: { sub?: string; onNav: (path: string) => void }) {
  const { t } = useI18n(), { message, modal } = App.useApp(), layout = useLayout()
  const controller = useModelCatalog(), loaded = controller.value
  const value = loaded || { revision: '', sources: [], models: [], drafts: [], baseUrl: '', uses: {} }
  const [requested, detail, id] = sub.split('/')
  const legacy = getHashParams().get('modelTab')
  const tab = requested === 'sources' ? 'catalog' : tabs.includes(requested) ? requested : legacy === 'prices' ? 'prices' : legacy === 'proxy' ? 'usage' : 'catalog'
  const billing = useGatewaySettings(tab === 'usage' || tab === 'prices')
  const [newSourceId, setNewSourceId] = useState(newID), [newModelId, setNewModelId] = useState(newID), [newConnectionModelId, setNewConnectionModelId] = useState(newID)
  const [sourceModelDrafts, setSourceModelDrafts] = useState<Record<string, CatalogModel[]>>({})
  const [sourceDrafts, setSourceDrafts] = useState<Record<string, ModelSource>>({}), [modelDrafts, setModelDrafts] = useState<Record<string, CatalogModel>>({})
  const navigate = (path: string) => onNav('capabilities/models/' + path)
  const back = () => navigate(tab)
  const error = controller.error && <Alert type="error" role="alert" message={t(controller.error)} action={<Button onClick={controller.retry}>{t('capabilities.models.reread')}</Button>} />
  const models = value?.models || [], sources = value?.sources || []
  const priceModels = [...new Set(models.flatMap(model => model.candidates.map(candidate => candidate.model)))]
  if (!loaded && tab !== 'usage' && tab !== 'prices') return <div className="tt-model-hub-scroll">{error || <Spin />}</div>
  const sourceBase: ModelSource = sources.find(source => source.id === id) || { id: newSourceId, name: '', baseUrl: '', protocol: 'openai-completions', authMode: 'api_key', apiKey: '' }
  const source = sourceDrafts[id] || { ...sourceBase, apiKey: '' }
  const modelBase: CatalogModel = models.find(model => model.id === id) || value.drafts.find(model => model.id === id) || { id: newModelId, name: '', protocol: sources[0]?.protocol || 'openai-completions', strategy: 'fixed', candidates: [{ sourceId: sources[0]?.id || '', model: '' }] }
  const model = modelDrafts[id] || modelBase
  const updateSource = (patch: Partial<ModelSource>) => setSourceDrafts(previous => ({ ...previous, [id]: { ...source, ...patch } }))
  const updateModel = (patch: Partial<CatalogModel>) => setModelDrafts(previous => ({ ...previous, [id]: { ...model, ...patch } }))
  const connectionModels = sourceModelDrafts[id] || (id === 'new' ? [{ id: newConnectionModelId, name: '', protocol: source.protocol, strategy: 'fixed' as const, candidates: [{ sourceId: source.id, model: '' }] }] : models.filter(model => model.candidates[0].sourceId === source.id))
  const updateConnectionModel = (modelId: string, patch: Partial<CatalogModel>) => setSourceModelDrafts(previous => ({ ...previous, [id]: connectionModels.map(model => model.id === modelId ? { ...model, ...patch } : model) }))
  const appendConnectionModel = () => setSourceModelDrafts(previous => ({ ...previous, [id]: [...connectionModels, { id: newID(), name: '', protocol: source.protocol, strategy: 'fixed', candidates: [{ sourceId: source.id, model: '' }] }] }))
  const validConnection = source.name.trim() && source.baseUrl.trim() && connectionModels.every(model => model.candidates[0].model.trim().length <= 200 && (model.candidates[0].model.trim() || !models.some(row => row.id === model.id) && !model.name.trim()))
  const validModel = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$/.test(model.id) && model.candidates.length > 0 && (model.strategy !== 'failover' || model.candidates.length > 1) && model.candidates.every(candidate => candidate.model.trim() && sources.some(source => source.id === candidate.sourceId)) && !models.some(row => row.id === model.id && row.id !== id)
  const saveSource = async () => {
    if (!validConnection || controller.busy) return
    const nextModels = connectionModels.filter(model => model.candidates[0].model.trim()).map(model => ({ ...model, name: model.name.trim() || model.candidates[0].model.trim(), protocol: source.protocol, candidates: [{ sourceId: source.id, model: model.candidates[0].model.trim() }, ...model.candidates.slice(1)] }))
    const nextByID = new Map(nextModels.map(model => [model.id, model]))
    const mergedModels = models.flatMap(model => model.candidates[0].sourceId !== source.id ? [model] : nextByID.has(model.id) ? [nextByID.get(model.id)!] : [])
    mergedModels.push(...nextModels.filter(model => !models.some(row => row.id === model.id)))
    const nextSources = sources.some(row => row.id === source.id) ? sources.map(row => row.id === source.id ? source : row) : [...sources, source]
    if (await controller.save({ ...value, sources: nextSources, models: mergedModels })) {
      setSourceDrafts(previous => { const next = { ...previous }; delete next[id]; return next })
      setSourceModelDrafts(previous => { const next = { ...previous }; delete next[id]; return next })
      if (id === 'new') { setNewSourceId(newID()); setNewConnectionModelId(newID()) }
      message.success(t('agent.models.saved')); back()
    }
  }
  const saveModel = async () => {
    const next = { ...model, name: model.name.trim() || model.candidates[0].model.trim(), candidates: model.strategy === 'fixed' ? model.candidates.slice(0, 1) : model.candidates }
    if (await controller.save({ ...value, models: [...models.filter(row => row.id !== next.id), next], drafts: value.drafts.filter(row => row.id !== next.id) })) {
      setModelDrafts(previous => { const n = { ...previous }; delete n[id]; return n }); if (id === 'new') setNewModelId(newID()); message.success(t('hub.modelSaved')); back()
    }
  }
  const submitModel = () => {
    if (!validModel || controller.busy) return
    const users = [...new Set(value.uses[model.id] || [])]
    if (users.length) modal.confirm({ className: 'tt-model-connection-confirm', title: t('agent.models.save'), content: t('hub.modelImpact', { users: users.join(', ') }), onOk: saveModel })
    else void saveModel()
  }
  const selectSource = (sourceId: string, index: number) => {
    const protocol = sources.find(source => source.id === sourceId)?.protocol || model.protocol
    updateModel({ ...(index === 0 ? { protocol } : {}), candidates: model.candidates.map((row, i) => i === index ? { ...row, sourceId } : row) })
  }
  const candidateFields = (index: number) => <>
    <label className="agent-settings-field">{t('hub.source')}<Select virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('hub.source')} value={model.candidates[index].sourceId || undefined} options={sources.map(source => ({ value: source.id, label: source.name }))} onChange={sourceId => selectSource(sourceId, index)} /></label>
    <label className="agent-settings-field">{t('hub.upstreamModel')}<Input aria-label={t('hub.upstreamModel')} value={model.candidates[index].model} onChange={event => updateModel({ candidates: model.candidates.map((row, i) => i === index ? { ...row, model: event.target.value } : row) })} /></label>
  </>
  const sourceEditor = <form className="agent-settings-form" onSubmit={event => { event.preventDefault(); if (validConnection && !controller.busy) modal.confirm({ className: 'tt-model-connection-confirm', title: t('hub.connectionApply'), okText: t('agent.models.save'), cancelText: t('common.cancel'), content: t('hub.sourceImpact'), onOk: saveSource }) }}>
    <label className="agent-settings-field">{t('hub.name')}<Input aria-label={t('hub.name')} value={source.name} maxLength={100} onChange={event => updateSource({ name: event.target.value })} /></label>
    <label className="agent-settings-field">{t('agent.models.baseUrl')}<Input aria-label={t('agent.models.baseUrl')} type="url" value={source.baseUrl} onChange={event => updateSource({ baseUrl: event.target.value })} placeholder="https://api.example.com/v1" /></label>
    <label className="agent-settings-field">{t('agent.models.apiKey')}<Input.Password aria-label={t('agent.models.apiKey')} autoComplete="new-password" visibilityToggle={false} value={source.apiKey} placeholder={t(source.hasKey ? 'agent.models.keyKept' : 'agent.models.keyPlaceholder')} onChange={event => updateSource({ apiKey: event.target.value })} /></label>
    <details><summary>{t('hub.connectionOptions')}</summary>
    <label className="agent-settings-field">{t('capabilities.models.protocol')}<Select virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('capabilities.models.protocol')} value={source.protocol} options={modelProtocols.map(value => ({ value, label: t('capabilities.models.protocol.' + value) }))} onChange={protocol => updateSource({ protocol })} /></label>
    <label className="agent-settings-field">{t('capabilities.models.authMode')}<Select virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('capabilities.models.authMode')} value={source.authMode} options={['api_key', 'bearer'].map(value => ({ value, label: t('capabilities.models.auth.' + value) }))} onChange={authMode => updateSource({ authMode })} /></label>
    </details>
    <fieldset className="tt-model-connection-models"><legend>{t('hub.tab.catalog')}</legend>
      {connectionModels.map(row => <div className="tt-model-connection-model" key={row.id}>
        <label className="agent-settings-field">{t('hub.upstreamModel')}<Input aria-label={t('hub.upstreamModel')} value={row.candidates[0].model} maxLength={200} onChange={event => updateConnectionModel(row.id, { candidates: [{ ...row.candidates[0], model: event.target.value }, ...row.candidates.slice(1)] })} /></label>
        <label className="agent-settings-field">{t('hub.displayName')}<Input aria-label={t('hub.displayName')} value={row.name} maxLength={100} onChange={event => updateConnectionModel(row.id, { name: event.target.value })} /></label>
        <Button danger onClick={() => setSourceModelDrafts(previous => ({ ...previous, [id]: connectionModels.filter(model => model.id !== row.id) }))}>{t('agent.proxy.remove')}</Button>
      </div>)}
      <Button icon={<PlusIcon />} onClick={appendConnectionModel}>{t('hub.addModel')}</Button>
    </fieldset>
    <div className="agent-settings-save"><Button onClick={back}>{t('common.back')}</Button><Button type="primary" htmlType="submit" loading={controller.busy} disabled={!validConnection || controller.busy}>{t('agent.models.save')}</Button></div>
  </form>
  const modelEditor = <form className="agent-settings-form" onSubmit={event => { event.preventDefault(); submitModel() }}>
    <label className="agent-settings-field">{t('hub.displayName')}<Input aria-label={t('hub.displayName')} value={model.name} maxLength={100} onChange={event => updateModel({ name: event.target.value })} /></label>
    {candidateFields(0)}
    {!sources.length && <Button icon={<PlusIcon />} onClick={() => navigate('catalog/source/new')}>{t('hub.addSource')}</Button>}
    <details><summary>{t('hub.strategy')}</summary>
      <label className="agent-settings-field">{t('hub.strategy')}<Select virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('hub.strategy')} value={model.strategy} options={['fixed', 'failover'].map(value => ({ value, label: t('hub.strategy.' + value) }))} onChange={strategy => updateModel({ strategy, candidates: model.candidates.slice(0, 1) })} /></label>
      {model.candidates.slice(1).map((_, offset) => <fieldset key={offset}><legend>{t('hub.backup', { index: offset + 1 })}</legend>
        {candidateFields(offset + 1)}
        <Button onClick={() => updateModel({ candidates: model.candidates.filter((_, i) => i !== offset + 1) })}>{t('agent.proxy.remove')}</Button>
      </fieldset>)}
      {model.strategy === 'failover' && <Button disabled={model.candidates.length >= 8} icon={<PlusIcon />} onClick={() => updateModel({ candidates: [...model.candidates, { sourceId: '', model: '' }] })}>{t('hub.addBackup')}</Button>}
      <p className="agent-settings-hint">{t('hub.failoverHint')}</p>
    </details>
    <p className="agent-settings-hint">{t('hub.availableHint')}</p>
    <div className="agent-settings-save"><Button onClick={back}>{t('common.back')}</Button><Button type="primary" htmlType="submit" disabled={!validModel || controller.busy} loading={controller.busy}>{t('agent.models.save')}</Button></div>
  </form>
  const editor = <>{error}{detail === 'source' ? sourceEditor : modelEditor}</>
  const editorTitle = t(detail === 'source' ? 'hub.editConnection' : 'hub.editModel')
  const rows = sources.map(source => {
    const attached = models.filter(model => model.candidates[0].sourceId === source.id)
    const backupUsed = models.some(model => model.candidates[0].sourceId !== source.id && model.candidates.some(candidate => candidate.sourceId === source.id))
    return <section className="tt-model-connection" key={source.id} aria-label={source.name}>
      <div className="tt-model-hub-row"><div><strong>{source.name}</strong>{source.name !== source.baseUrl && <small>{source.baseUrl}</small>}</div>
        <Button onClick={() => navigate('catalog/source/' + source.id)}>{t('hub.edit')}</Button>
        <Popconfirm classNames={{ root: 'tt-model-connection-confirm' }} title={t('hub.deleteConnection')} onConfirm={() => controller.save({ ...value, sources: sources.filter(row => row.id !== source.id), models: models.filter(model => model.candidates[0].sourceId !== source.id) })}><button type="button" className="tt-act danger" disabled={backupUsed}>{t('capabilities.models.deleteAction')}</button></Popconfirm>
      </div>
      {attached.map(model => <div className="tt-model-hub-row tt-model-connection-child" key={model.id}><div><strong>{model.name}</strong>{model.name !== model.candidates[0].model && <small>{model.candidates[0].model}</small>}</div>
        <Button onClick={() => navigate('catalog/model/' + model.id)}>{t('hub.strategy')}</Button><Popconfirm classNames={{ root: 'tt-model-connection-confirm' }} title={t('hub.delete')} onConfirm={() => controller.save({ ...value, models: models.filter(row => row.id !== model.id), drafts: value.drafts.filter(row => row.id !== model.id) })}><button type="button" className="tt-act danger">{t('capabilities.models.deleteAction')}</button></Popconfirm>
      </div>)}
      {backupUsed && <p className="agent-settings-hint">{t('hub.connectionBackupUsed')}</p>}
      <Button className="tt-model-connection-add" icon={<PlusIcon />} onClick={() => {
        setSourceModelDrafts(previous => ({ ...previous, [source.id]: [...(previous[source.id] || attached), { id: newID(), name: '', protocol: source.protocol, strategy: 'fixed', candidates: [{ sourceId: source.id, model: '' }] }] }))
        navigate('catalog/source/' + source.id)
      }}>{t('hub.addModel')}</Button>
    </section>
  })
  const consumers = Object.entries(value.uses).filter(([, users]) => users.length)
  return <div className="tt-model-hub">
    {(!detail || !layout.phone) && <div className="tt-model-hub-scroll">
      {error}
      <details className="tt-model-hub-entry"><summary><LinkIcon />{t('hub.entry')}</summary><p>{t('hub.entryHint')}</p><code>{value.baseUrl}</code><p>{t('hub.continuationHint')}</p></details>
      <Tabs activeKey={tab} onChange={key => navigate(key)} items={tabs.map(key => ({ key, label: t('hub.tab.' + key) }))} />
      {tab === 'usage' || tab === 'prices' ? <><GatewaySettingsForm controller={billing} mode={tab === 'usage' ? 'proxy' : 'prices'} active models={priceModels} /><GatewayReconciliation controller={billing} /></>
        : <><div className="tt-model-hub-actions"><Button type="primary" icon={<PlusIcon />} onClick={() => navigate('catalog/source/new')}>{t('hub.addConnection')}</Button><Button onClick={() => onNav('capabilities/agents')}>{t('hub.configureAgents')}</Button></div>{rows.length ? rows : <p>{t('hub.empty.connections')}</p>}
        {!!consumers.length && <section className="tt-model-hub-consumers"><div className="tt-model-hub-actions"><h3>{t('hub.consumers')}</h3></div>{consumers.map(([model, users]) => <div className="tt-model-hub-row" key={model}><div><strong>{models.find(row => row.id === model)?.name || model}</strong><small>{[...new Set(users)].join(', ')}</small></div><Button onClick={() => onNav('capabilities/agents/' + users[0] + '/models')}>{t('hub.configure')}</Button></div>)}</section>}</>}
    </div>}
    {detail && (layout.phone ? <MobileSubPage title={editorTitle} search={false} onBack={back} manageHistory={false} keepBottomNav><div className="tt-model-hub-scroll">{editor}</div></MobileSubPage> : <aside className="tt-model-hub-detail"><div className="tt-model-hub-detail-head"><h3>{editorTitle}</h3><Button onClick={back}>{t('common.back')}</Button></div><div className="tt-model-hub-scroll">{editor}</div></aside>)}
  </div>
}
