import { useState } from 'react'
import { Alert, App, Button, Input, Popconfirm, Select, Spin, Tabs } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { getHashParams } from '../../route-hash'
import { PlusIcon, LinkIcon } from '../../icons'
import { useSettingsDraft } from '../settings/settings-draft'
import MobileSubPage from '../MobileSubPage'
import LocalModelSources from './LocalModelSources'
import ModelSourceEditor, { initialSourceDraft, type SourceDraft } from './ModelSourceEditor'
import { GatewaySettingsForm, GatewayReconciliation, useGatewaySettings } from '../settings/gateway-settings'
import { useModelCatalog, type ModelSource, type CatalogModel } from './model-hub-api'
import '../settings/agent-settings.css'
import './model-hub.css'

const tabs = ['catalog', 'usage', 'prices']
const newID = () => globalThis.crypto?.randomUUID?.() || Date.now().toString(36)
export default function ModelHub({ sub = '', onNav, embedded = false }: { sub?: string; onNav: (path: string) => void; embedded?: boolean }) {
  const { t } = useI18n(), { message, modal } = App.useApp(), layout = useLayout()
  const controller = useModelCatalog(), loaded = controller.value
  const value = loaded || { revision: '', sources: [], models: [], drafts: [], baseUrl: '', uses: {} }
  const [requested, detail, id] = sub.split('/')
  const legacy = getHashParams().get('modelTab')
  const tab = requested === 'sources' ? 'catalog' : tabs.includes(requested) ? requested : legacy === 'prices' ? 'prices' : legacy === 'proxy' ? 'usage' : 'catalog'
  const billing = useGatewaySettings(tab === 'usage' || tab === 'prices')
  const [newSourceId, setNewSourceId] = useState(newID), [newModelId, setNewModelId] = useState(newID)
  const [sourceDrafts, setSourceDrafts] = useState<Record<string, SourceDraft>>({}), [modelDrafts, setModelDrafts] = useState<Record<string, CatalogModel>>({})
  const draftNotice = useSettingsDraft('onboarding-model-hub', { sourceDrafts, modelDrafts }, { sourceDrafts: {}, modelDrafts: {} }, draft => { setSourceDrafts(draft.sourceDrafts); setModelDrafts(draft.modelDrafts) }, embedded)
  const navigate = (path: string) => onNav('capabilities/models/' + path)
  const back = () => navigate(tab)
  const error = controller.error && <Alert type="error" role="alert" message={t(controller.error)} action={<Button onClick={controller.retry}>{t('capabilities.models.reread')}</Button>} />
  const models = value?.models || [], sources = value?.sources || []
  const priceModels = [...new Set(models.flatMap(model => model.candidates.map(candidate => candidate.model)).concat(models.flatMap(model => [model.id, ...model.candidates.map(candidate => candidate.sourceId + "/" + candidate.model)])))]
  if (!loaded && tab !== 'usage' && tab !== 'prices') return <div className="tt-model-hub-scroll">{error || <Spin />}</div>
  const sourceBase: ModelSource = sources.find(source => source.id === id) || { id: newSourceId, name: '', baseUrl: '', protocol: 'openai-completions', authMode: 'api_key', apiKey: '' }
  const sourceDraft = sourceDrafts[id] || initialSourceDraft(sourceBase, id !== 'new')
  const modelBase: CatalogModel = models.find(model => model.id === id) || value.drafts.find(model => model.id === id) || { id: newModelId, name: '', protocol: sources[0]?.protocol || 'openai-completions', strategy: 'fixed', candidates: [{ sourceId: sources[0]?.id || '', model: '' }] }
  const model = modelDrafts[id] || modelBase
  const updateModel = (patch: Partial<CatalogModel>) => setModelDrafts(previous => ({ ...previous, [id]: { ...model, ...patch } }))
  const validModel = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$/.test(model.id) && model.candidates.length > 0 && (model.strategy !== 'failover' || model.candidates.length > 1) && model.candidates.every(candidate => candidate.model.trim() && sources.some(source => source.id === candidate.sourceId)) && !models.some(row => row.id === model.id && row.id !== id)
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
  const sourceEditor = <ModelSourceEditor key={sourceBase.id} draft={sourceDraft} onChange={draft => setSourceDrafts(previous => ({ ...previous, [id]: draft }))} catalog={value} busy={controller.busy} error={controller.error} retry={controller.retry} onBack={back} onSave={async next => {
    const saved = await controller.save(next)
    if (saved) {
      setSourceDrafts(previous => { const next = { ...previous }; delete next[id]; return next })
      if (id === 'new') setNewSourceId(newID())
    }
    return saved
  }} />
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
  const editor = detail === 'local' ? <LocalModelSources onImported={() => { controller.retry(); back() }} /> : detail === 'source' ? sourceEditor : <div className="tt-model-hub-scroll">{error}{modelEditor}</div>
  const editorTitle = t(detail === 'local' ? 'hub.local.title' : detail === 'source' ? id === 'new' ? 'hub.addSource' : 'hub.editSource' : 'hub.editModel')
  const rows = sources.map(source => {
    const attached = models.filter(model => model.candidates[0].sourceId === source.id)
    const backupUsed = models.some(model => model.candidates[0].sourceId !== source.id && model.candidates.some(candidate => candidate.sourceId === source.id))
    return <section className="tt-model-connection" key={source.id} aria-label={source.name}>
      <div className="tt-model-hub-row"><div><strong>{source.name}</strong>{source.name !== source.baseUrl && <small>{source.baseUrl}</small>}</div>
        <Button onClick={() => { setSourceDrafts(previous => ({ ...previous, [source.id]: { ...(previous[source.id] || initialSourceDraft(source, true)), editing: true } })); navigate('catalog/source/' + source.id) }}>{t('hub.directory.configureSource')}</Button>
        <Popconfirm classNames={{ root: 'tt-model-connection-confirm' }} title={t('hub.deleteConnection')} onConfirm={() => controller.save({ ...value, sources: sources.filter(row => row.id !== source.id), models: models.filter(model => model.candidates[0].sourceId !== source.id) })}><button type="button" className="tt-act danger" disabled={backupUsed}>{t('capabilities.models.deleteAction')}</button></Popconfirm>
      </div>
      {attached.map(model => <div className="tt-model-hub-row tt-model-connection-child" key={model.id}><div><strong>{model.name}</strong>{model.name !== model.candidates[0].model && <small>{model.candidates[0].model}</small>}</div>
        <Button onClick={() => navigate('catalog/model/' + model.id)}>{t('hub.strategy')}</Button><Popconfirm classNames={{ root: 'tt-model-connection-confirm' }} title={t('hub.delete')} onConfirm={() => controller.save({ ...value, models: models.filter(row => row.id !== model.id), drafts: value.drafts.filter(row => row.id !== model.id) })}><button type="button" className="tt-act danger">{t('capabilities.models.deleteAction')}</button></Popconfirm>
      </div>)}
      {backupUsed && <p className="agent-settings-hint">{t('hub.connectionBackupUsed')}</p>}
      <Button className="tt-model-connection-add" icon={<PlusIcon />} onClick={() => navigate('catalog/source/' + source.id)}>{t('hub.directory.addMore')}</Button>
    </section>
  })
  const consumers = Object.entries(value.uses).filter(([, users]) => users.length)
  if (embedded && detail) return <div className="onboarding-model-editor">{draftNotice}{editor}</div>
  return <div className={embedded ? 'tt-model-hub onboarding-model-hub' : 'tt-model-hub'}>
    {draftNotice}
    {(!detail || !layout.phone) && <div className="tt-model-hub-scroll">
      {error}
      <details className="tt-model-hub-entry"><summary><LinkIcon />{t('hub.entry')}</summary><p>{t('hub.entryHint')}</p><code>{value.baseUrl}</code><p>{t('hub.continuationHint')}</p></details>
      <Tabs activeKey={tab} onChange={key => navigate(key)} items={tabs.map(key => ({ key, label: t('hub.tab.' + key) }))} />
      {tab === 'usage' || tab === 'prices' ? <><GatewaySettingsForm controller={billing} mode={tab === 'usage' ? 'proxy' : 'prices'} active models={priceModels} /><GatewayReconciliation controller={billing} /></>
        : <><div className="tt-model-hub-actions"><Button type="primary" icon={<PlusIcon />} onClick={() => navigate('catalog/source/new')}>{t('hub.addSource')}</Button><Button onClick={() => navigate('catalog/local')}>{t('hub.local.title')}</Button><Button onClick={() => onNav('capabilities/agents')}>{t('hub.configureAgents')}</Button></div>{rows.length ? rows : <p>{t('hub.empty.connections')}</p>}
        {!!consumers.length && <section className="tt-model-hub-consumers"><div className="tt-model-hub-actions"><h3>{t('hub.consumers')}</h3></div>{consumers.map(([model, users]) => <div className="tt-model-hub-row" key={model}><div><strong>{models.find(row => row.id === model)?.name || model}</strong><small>{[...new Set(users)].join(', ')}</small></div><Button onClick={() => onNav('capabilities/agents/' + users[0] + '/models')}>{t('hub.configure')}</Button></div>)}</section>}</>}
    </div>}
    {detail && (layout.phone ? <MobileSubPage title={editorTitle} search={false} onBack={back} manageHistory={false} keepBottomNav>{editor}</MobileSubPage> : <aside className="tt-model-hub-detail"><div className="tt-model-hub-detail-head"><h3>{editorTitle}</h3><Button onClick={back}>{t('common.back')}</Button></div>{editor}</aside>)}
  </div>
}
