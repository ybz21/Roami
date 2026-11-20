import { useEffect, useRef, useState, type ReactNode } from 'react'
import { App } from 'antd'
import { Alert, Button, Checkbox, Input, Select, Popconfirm, Pagination } from './model-controls'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { ChevronDown, LinkIcon, PlusIcon, SearchIcon } from '../../icons'
import { configuredSourceModels } from './configured-source-models'
import { catalogFailure, modelProtocols, openRouterConnection, type ModelCatalog, type ModelSource } from './model-hub-api'

export type SourceDraft = {
  source: ModelSource
  original: ModelSource
  managing?: boolean
  editing: boolean
  directory: string[] | null
  directoryNames?: Record<string, string>
  selected: string[]
  query: string
  manual: string
  removed?: string[]
  fetchRequested?: boolean
  manualOpen: boolean
}
export const initialSourceDraft = (source: ModelSource, existing: boolean): SourceDraft => ({ source: { ...source, apiKey: '' }, original: source, editing: !existing, directory: null, selected: [], query: '', manual: '', manualOpen: false })
const connectionKey = (source: ModelSource) => JSON.stringify([source.id, source.connector, source.baseUrl, source.apiKey, source.protocol, source.authMode])
const sourceName = (source: ModelSource) => {
  if (source.name.trim()) return source.name.trim()
  try { return new URL(source.baseUrl).host } catch { return source.baseUrl }
}

export default function ModelSourceEditor({ draft, onChange, catalog, busy, error, retry, onSave, onBack, onEditModel, pricing, authentication, management, initialAuthorizationOpen = false }: {
  draft: SourceDraft; onChange: (draft: SourceDraft) => void; catalog: ModelCatalog; busy: boolean; error: string; retry: () => void
  onSave: (catalog: ModelCatalog) => Promise<boolean>; onBack: () => void
  pricing?: ReactNode; initialAuthorizationOpen?: boolean; authentication?: ReactNode; management?: ReactNode; onEditModel: (id: string) => void
}) {
  const { t, locale } = useI18n(), { message } = App.useApp()
  const [confirming, setConfirming] = useState(false), [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false), [readError, setReadError] = useState('')
  const request = useRef<AbortController | null>(null)
  const current = useRef(draft); current.current = draft
  const source = draft.source, existing = catalog.sources.find(row => row.id === source.id)
  const key = connectionKey(source)
  useEffect(() => { request.current?.abort(); request.current = null; setLoading(false); setReadError(''); return () => request.current?.abort() }, [key])
  const patch = (next: Partial<SourceDraft>) => onChange({ ...draft, ...next })
  const updateSource = (next: Partial<ModelSource>) => {
    const updated = { ...source, ...next }
    if (connectionKey(updated) !== key) { request.current?.abort(); patch({ source: updated, directory: null, fetchRequested: false }) }
    else patch({ source: updated })
  }
  const normalizedURL = source.baseUrl.trim().replace(/\/+$/, '')
  const openRouter = source.connector === openRouterConnection.connector
  const canChangeConnector = !!existing && normalizedURL === openRouterConnection.baseUrl && source.protocol === openRouterConnection.protocol
  let validURL = false
  let publicHTTP = false
  try {
    const url = new URL(normalizedURL)
    const local = ['localhost', '[::1]'].includes(url.hostname) || /^(127|10)\.\d+\.\d+\.\d+$|^192\.168\.\d+\.\d+$|^172\.(1[6-9]|2\d|3[01])\.\d+\.\d+$|^\[f[cd][\da-f]{2}:/i.test(url.hostname)
    publicHTTP = url.protocol === 'http:' && !local
    validURL = normalizedURL.length <= 2000 && !url.username && !url.password && !url.search && !url.hash && (url.protocol === 'https:' || url.protocol === 'http:' && local)
  } catch { /* Validated before reading or saving. */ }
  const urlError = !validURL && normalizedURL ? t(publicHTTP ? 'hub.directory.publicHTTP' : 'hub.directory.invalidURL') : ''
  const needsKey = !!existing?.hasKey && normalizedURL !== existing.baseUrl && !source.apiKey
  const validConnection = validURL && !needsKey
  const attached = configuredSourceModels(catalog.models, source.id)
  const added = new Set(attached.map(model => model.candidates[0].model))
  const manual = [...new Set(draft.manual.split(/\r?\n/).map(value => value.trim()).filter(Boolean))]
  const invalidManual = manual.some(value => new TextEncoder().encode(value).length > 200 || /[\r\n\x00]/.test(value))
  const selected = draft.directory ? draft.selected.filter(value => draft.directory!.includes(value)) : []
  const additions = [...new Set([...selected, ...manual])].filter(value => !added.has(value))
  const removed = new Set((draft.removed || []).filter(value => added.has(value) && !manual.includes(value)))
  const removedCount = attached.filter(model => removed.has(model.candidates[0].model)).length
  const sourceConflict = !!existing && (connectionKey(existing) !== connectionKey(draft.original) || existing.name !== draft.original.name)
  const changedConnection = !!existing && (connectionKey({ ...existing, apiKey: '' }) !== key || source.name.trim() !== existing.name)
  const overLimit = catalog.models.length - removedCount + additions.length > 1000
  const managing = !existing || !!draft.managing
  const connectionOnly = !!existing && draft.editing
  const hasKey = !!(source.hasKey || source.apiKey?.trim())
  const canRead = validConnection && (!openRouter || hasKey)
  const hasChanges = !existing || (connectionOnly ? changedConnection : additions.length > 0 || removedCount > 0)
  const canSave = !sourceConflict && validConnection && (!openRouter || hasKey) && !invalidManual && !overLimit && hasChanges && !busy && !loading
  const number = (value: number) => new Intl.NumberFormat(locale).format(value)
  const query = draft.query.trim().toLowerCase()
  const savedNames = new Map<string, string[]>()
  for (const model of attached) {
    const id = model.candidates[0].model
    savedNames.set(id, [...(savedNames.get(id) || []), model.name])
  }
  const listed = openRouter && draft.directory !== null ? draft.directory : [...new Set([...(draft.directory || []), ...added])]
  const visible = listed.filter(id =>
    [id, draft.directory === null ? '' : draft.directoryNames?.[id] || '', ...(savedNames.get(id) || [])].some(value => value.toLowerCase().includes(query)),
  )
  const currentPage = Math.min(page, Math.max(1, Math.ceil(visible.length / 30)))
  useEffect(() => { setPage(1) }, [draft.query, draft.directory])
  const selectable = visible
  const checked = (value: string) => added.has(value) ? !removed.has(value) : draft.selected.includes(value)
  const selectedVisible = selectable.filter(checked)
  const selectModels = (values: string[], enabled: boolean) => patch({ selected: enabled ? [...new Set([...draft.selected, ...values.filter(value => !added.has(value))])] : draft.selected.filter(value => !values.includes(value)), removed: enabled ? [...removed].filter(value => !values.includes(value)) : [...new Set([...removed, ...values.filter(value => added.has(value))])] })
  const read = async () => {
    if (!canRead || request.current || busy) return
    const abort = new AbortController(); request.current = abort
    setLoading(true); setReadError(''); if (existing) patch({ managing: true })
    try {
      const { data } = await api('POST', '/agent/model-gateway/catalog/discover', { revision: catalog.revision, source: { ...source, baseUrl: normalizedURL } }, { signal: abort.signal })
      if (!abort.signal.aborted) {
        const directoryNames = Object.fromEntries((data.details || []).map((row: { id: string; name?: string }) => [row.id, row.name || '']))
        onChange({ ...current.current, directory: data.models, directoryNames, managing: true, editing: false, fetchRequested: false, selected: current.current.selected.filter(value => data.models.includes(value)) })
      }
    } catch (cause: any) {
      if (!abort.signal.aborted) { onChange({ ...current.current, fetchRequested: false }); setReadError(cause?.apiError?.code === 'MODEL_LIST_UNAUTHORIZED' ? 'hub.directory.unauthorized' : cause?.apiError?.code === 'MODEL_LIST_UNSUPPORTED' ? 'hub.directory.unsupported' : cause?.apiError?.code === 'MODEL_LIST_FAILED' ? 'hub.directory.failed' : catalogFailure(cause)) }
    } finally { if (request.current === abort) { request.current = null; setLoading(false) } }
  }
  useEffect(() => {
    if (draft.fetchRequested && canRead && !busy) void read()
  }, [draft.fetchRequested, canRead, busy])
  const save = async () => {
    if (!canSave) return
    const nextSource = existing && !connectionOnly ? {...existing,apiKey:''} : { ...source, name: sourceName(source), baseUrl: normalizedURL }
    const nextModels = connectionOnly ? catalog.models.map(model => !model.aggregate && model.candidates[0].sourceId === source.id ? {...model,protocol:source.protocol} : model) : catalog.models.filter(model => model.aggregate || model.candidates[0].sourceId !== source.id || !removed.has(model.candidates[0].model)).map(model => !model.aggregate && model.candidates[0].sourceId === source.id ? { ...model, protocol: source.protocol } : model)
    for (const model of connectionOnly ? [] : additions) nextModels.push({ id: globalThis.crypto?.randomUUID?.() || 'model-' + Math.random().toString(36).slice(2), name: model, protocol: source.protocol, strategy: 'fixed', candidates: [{ sourceId: source.id, model }] })
    if (await onSave({ ...catalog, sources: existing ? catalog.sources.map(row => row.id === source.id ? nextSource : row) : [...catalog.sources, nextSource], models: nextModels })) { message.success(t('agent.models.saved')); if (!existing) onBack() }
  }
  const submit = () => {
    if (!canSave) return
    if (connectionOnly || removedCount > 0) setConfirming(true)
    else void save()
  }
  return <form className="tt-model-source-editor" onSubmit={event => { event.preventDefault(); submit() }}>
    <Popconfirm danger={removedCount > 0} open={confirming} onOpenChange={setConfirming} title={t(removedCount ? 'hub.directory.applyModels' : 'hub.sourceApply')} description={t(removedCount ? 'hub.directory.removeImpact' : 'hub.sourceImpact')} okText={t('agent.models.save')} onConfirm={save} />
    <div className="tt-model-source-content">
      {authentication && <details className="tt-model-source-authorization" open={initialAuthorizationOpen || undefined}><summary>{t('modelInteraction.authorization')}</summary><div>{authentication}</div></details>}
      {sourceConflict && <Alert type="warning" role="alert" message={t('hub.directory.sourceChanged')} action={<Button onClick={() => onChange({ ...draft, source: { ...existing!, apiKey: '' }, original: existing!, directory: null, editing: true })}>{t('hub.directory.useLatest')}</Button>} />}
      {error && <Alert type="error" role="alert" message={t(error)} action={<Button onClick={retry}>{t('capabilities.models.reread')}</Button>} />}
      <section className="tt-model-source-connection" aria-label={t('hub.source')}>
        {source.pluginSourceId && draft.editing ? <label className="agent-settings-field">{t('hub.directory.sourceName')}<Input aria-label={t('hub.name')} value={source.name} maxLength={100} onChange={event => updateSource({ name: event.target.value })} /></label> : draft.editing ? <>
          {canChangeConnector && <label className="agent-settings-field">{t('modelInteraction.sourceType')}<Select virtual={false} aria-label={t('modelInteraction.sourceType')} value={source.connector || 'api'} options={[{ value: 'api', label: t('modelInteraction.sourceType.api') }, { value: 'openrouter-free', label: t('hub.openRouter.name') }]} onChange={value => updateSource(value === 'openrouter-free' ? openRouterConnection : { connector: undefined })} /></label>}
          <label className="agent-settings-field">{t('agent.models.baseUrl')}<Input aria-label={t('agent.models.baseUrl')} aria-invalid={!!urlError} aria-describedby={urlError ? 'model-source-url-error' : undefined} type="url" value={source.baseUrl} readOnly={openRouter} maxLength={2000} placeholder="https://api.example.com/v1" onChange={event => updateSource({ baseUrl: event.target.value })} />{urlError && <span id="model-source-url-error" className="tt-model-source-warning" role="status">{urlError}</span>}</label>
          {!openRouter && <label className="agent-settings-field">{t('capabilities.models.protocol')}<Select virtual={false} aria-label={t('capabilities.models.protocol')} value={source.protocol} options={modelProtocols.map(value => ({ value, label: t('capabilities.models.protocol.' + value) }))} onChange={protocol => updateSource({ protocol })} /></label>}
          <label className="agent-settings-field">{t('modelIdentity.providerKey')}<Input.Password aria-label={t('modelIdentity.providerKey')} autoComplete="new-password" visibilityToggle={false} value={source.apiKey} maxLength={8192} placeholder={t(source.hasKey ? 'agent.models.keyKept' : 'agent.models.keyPlaceholder')} onChange={event => updateSource({ apiKey: event.target.value })} /></label>
          {needsKey && <p className="tt-model-source-warning" role="alert">{t('agent.models.newEndpointKey')}</p>}
          <details className="tt-model-source-options"><summary>{t('hub.connectionOptions')}<ChevronDown /></summary><div>
            <label className="agent-settings-field">{t('hub.directory.sourceName')}<Input aria-label={t('hub.name')} value={source.name} maxLength={100} placeholder={t('hub.directory.autoName')} onChange={event => updateSource({ name: event.target.value })} /></label>
            {!openRouter && <label className="agent-settings-field">{t('capabilities.models.authMode')}<Select virtual={false} aria-label={t('capabilities.models.authMode')} value={source.authMode} options={['api_key', 'bearer'].map(value => ({ value, label: t('capabilities.models.auth.' + value) }))} onChange={authMode => updateSource({ authMode })} /></label>}
          </div></details>
        </> : <div className="tt-model-source-summary"><LinkIcon size={18} /><div><strong>{sourceName(source)}</strong>{sourceName(source) !== source.baseUrl && <small>{source.baseUrl}</small>}</div><button type="button" className="tt-act" disabled={busy || draft.managing} onClick={() => patch({ editing: true, managing: false })}>{t('hub.directory.changeConnection')}</button></div>}
        {!connectionOnly && <div className="tt-model-source-read"><Button type={draft.directory === null ? 'primary' : 'default'} loading={loading} disabled={!canRead || busy} onClick={() => void read()}>{t(openRouter ? 'hub.openRouter.fetch' : existing && !draft.managing ? 'modelInteraction.manageModels' : existing && draft.directory === null ? 'hub.directory.updateModels' : draft.directory === null ? 'hub.directory.fetch' : 'hub.directory.refetch')}</Button>{!existing && draft.directory === null && <span>{t('hub.directory.readHint')}</span>}</div>}
        {readError && <Alert type="warning" role="alert" message={t(readError)} />}
        {management}
      </section>
      {pricing}
      {!connectionOnly && (draft.directory !== null || !!existing) && <section className="tt-model-directory" aria-label={t('hub.directory.title')} aria-busy={loading}>
        <div className="tt-model-directory-heading"><h3>{t(draft.directory === null ? 'orchestration.configuredModels' : 'hub.directory.title')}</h3>{(draft.directory?.length || attached.length) > 0 && <span role="status">{t('hub.directory.total', { count: number(draft.directory?.length ?? attached.length) })}</span>}</div>
        {!!(draft.directory?.length || attached.length) && <Input aria-label={t('hub.directory.search')} placeholder={t('hub.directory.search')} prefix={<SearchIcon />} onPressEnter={event => event.preventDefault()} allowClear value={draft.query} onChange={event => patch({ query: event.target.value })} />}
        {managing && !!(draft.directory?.length || attached.length) && <div className="tt-model-directory-selection"><Checkbox checked={!!selectable.length && selectedVisible.length === selectable.length} indeterminate={selectedVisible.length > 0 && selectedVisible.length < selectable.length} disabled={!selectable.length} onChange={event => selectModels(selectable, event.target.checked)}>{t(draft.query ? 'hub.directory.selectMatches' : 'hub.directory.selectAll')}</Checkbox>{!!selected.length && <button type="button" className="tt-act" onClick={() => patch({ selected: [] })}>{t('hub.directory.clear')}</button>}</div>}
        <div className="tt-model-directory-list">{visible.slice((currentPage - 1) * 30, currentPage * 30).map(model => {
          const saved = attached.filter(row => row.candidates[0].model === model)
          return <div className="tt-model-directory-row" key={model}>{managing ? <Checkbox disabled={busy || loading} checked={checked(model)} onChange={event => selectModels([model], event.target.checked)}><span>{model}</span></Checkbox> : <strong className="tt-model-directory-name">{model}</strong>}{!!saved.length && <div className="tt-model-directory-actions">{draft.directory !== null && !draft.directory.includes(model) && <span className="tt-model-source-warning">{t('hub.directory.notListed')}</span>}{saved.map(row => <button key={row.id} type="button" className="tt-act" disabled={busy || loading} aria-label={t('hub.directory.editModel', { model: row.name })} onClick={() => onEditModel(row.id)}>{saved.length > 1 ? t('hub.directory.editModel', { model: row.name }) : t('capabilities.edit')}</button>)}</div>}</div>
        })}</div>
        {!visible.length && <p className="agent-settings-hint">{t(listed.length ? 'hub.directory.noMatches' : openRouter && draft.directory !== null ? 'hub.openRouter.empty' : 'orchestration.noConfiguredModels')}</p>}
      {visible.length > 30 && <Pagination current={currentPage} total={visible.length} pageSize={30} onChange={setPage} />}
      </section>}
      {managing && !connectionOnly && !source.pluginSourceId && !openRouter && <section className="tt-model-source-manual">
        <button type="button" className="tt-act" aria-expanded={draft.manualOpen} onClick={() => patch({ manualOpen: !draft.manualOpen })}><PlusIcon />{t('hub.directory.manual')}</button>
        {draft.manualOpen && <label className="agent-settings-field">{t('hub.directory.manualHint')}<Input.TextArea aria-label={t('hub.directory.manual')} rows={4} value={draft.manual} onChange={event => patch({ manual: event.target.value })} />{invalidManual && <span className="tt-model-source-warning" role="alert">{t('hub.directory.invalidManual')}</span>}</label>}
      </section>}
      {overLimit && <Alert type="warning" role="alert" message={t('hub.directory.limit')} />}
    </div>
    {(draft.editing || draft.managing || !existing) && <footer className="tt-model-source-footer"><span role="status">{t(connectionOnly ? 'modelInteraction.connectionScope' : removedCount ? 'hub.directory.changes' : additions.length ? 'hub.directory.selected' : existing ? 'hub.directory.unchanged' : 'hub.directory.connectionOnly', { count: number(additions.length), removed: number(removedCount) })}</span><div className="tt-model-source-footer-actions">{existing && <Button disabled={busy || loading} onClick={() => onChange(initialSourceDraft(existing, true))}>{t('common.cancel')}</Button>}<Button type="primary" htmlType="submit" loading={busy} disabled={!canSave}>{t(!connectionOnly && existing && (additions.length || removedCount) ? 'hub.directory.applyModels' : !connectionOnly && additions.length ? 'hub.directory.saveModels' : 'agent.models.save', { count: number(additions.length) })}</Button></div></footer>}
  </form>
}
