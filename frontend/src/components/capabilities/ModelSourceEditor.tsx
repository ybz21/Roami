import { useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Checkbox, Input, Select } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { CheckIcon, ChevronDown, LinkIcon, PlusIcon, SearchIcon } from '../../icons'
import { catalogFailure, modelProtocols, type ModelCatalog, type ModelSource } from './model-hub-api'

export type SourceDraft = {
  source: ModelSource
  original: ModelSource
  editing: boolean
  directory: string[] | null
  selected: string[]
  query: string
  manual: string
  manualOpen: boolean
}
export const initialSourceDraft = (source: ModelSource, existing: boolean): SourceDraft => ({ source: { ...source, apiKey: '' }, original: source, editing: !existing, directory: null, selected: [], query: '', manual: '', manualOpen: false })
const connectionKey = (source: ModelSource) => JSON.stringify([source.id, source.baseUrl, source.apiKey, source.protocol, source.authMode])
const sourceName = (source: ModelSource) => {
  if (source.name.trim()) return source.name.trim()
  try { return new URL(source.baseUrl).host } catch { return source.baseUrl }
}

export default function ModelSourceEditor({ draft, onChange, catalog, busy, error, retry, onSave, onBack }: {
  draft: SourceDraft; onChange: (draft: SourceDraft) => void; catalog: ModelCatalog; busy: boolean; error: string; retry: () => void
  onSave: (catalog: ModelCatalog) => Promise<boolean>; onBack: () => void
}) {
  const { t, locale } = useI18n(), { modal, message } = App.useApp()
  const [loading, setLoading] = useState(false), [readError, setReadError] = useState('')
  const request = useRef<AbortController | null>(null)
  const current = useRef(draft); current.current = draft
  const source = draft.source, existing = catalog.sources.find(row => row.id === source.id)
  const key = connectionKey(source)
  useEffect(() => { request.current?.abort(); request.current = null; setLoading(false); setReadError(''); return () => request.current?.abort() }, [key])
  const patch = (next: Partial<SourceDraft>) => onChange({ ...draft, ...next })
  const updateSource = (next: Partial<ModelSource>) => {
    const updated = { ...source, ...next }
    if (connectionKey(updated) !== key) { request.current?.abort(); patch({ source: updated, directory: null }) }
    else patch({ source: updated })
  }
  const normalizedURL = source.baseUrl.trim().replace(/\/+$/, '')
  let validURL = false
  try { const url = new URL(normalizedURL); validURL = normalizedURL.length <= 2000 && !url.username && !url.password && !url.search && !url.hash && (url.protocol === 'https:' || url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) } catch { /* Validated before reading or saving. */ }
  const needsKey = !!existing?.hasKey && normalizedURL !== existing.baseUrl && !source.apiKey
  const validConnection = validURL && !needsKey
  const attached = catalog.models.filter(model => model.candidates[0].sourceId === source.id)
  const added = new Set(attached.map(model => model.candidates[0].model))
  const manual = [...new Set(draft.manual.split(/\r?\n/).map(value => value.trim()).filter(Boolean))]
  const invalidManual = manual.some(value => new TextEncoder().encode(value).length > 200 || /[\r\n\x00]/.test(value))
  const selected = draft.directory ? draft.selected.filter(value => draft.directory!.includes(value)) : []
  const additions = [...new Set([...selected, ...manual])].filter(value => !added.has(value))
  const sourceConflict = !!existing && (connectionKey(existing) !== connectionKey(draft.original) || existing.name !== draft.original.name)
  const changedConnection = !!existing && (connectionKey({ ...existing, apiKey: '' }) !== key || source.name.trim() !== existing.name)
  const overLimit = catalog.models.length + additions.length > 1000
  const canSave = !sourceConflict && validConnection && !invalidManual && !overLimit && (additions.length > 0 || changedConnection) && !busy && !loading
  const number = (value: number) => new Intl.NumberFormat(locale).format(value)
  const visible = (draft.directory || []).filter(value => value.toLowerCase().includes(draft.query.toLowerCase()))
  const selectable = visible.filter(value => !added.has(value))
  const selectedVisible = selectable.filter(value => draft.selected.includes(value))
  const read = async () => {
    if (!validConnection || request.current || busy) return
    const abort = new AbortController(); request.current = abort
    setLoading(true); setReadError('')
    try {
      const { data } = await api('POST', '/agent/model-gateway/catalog/discover', { revision: catalog.revision, source: { ...source, baseUrl: normalizedURL } }, { signal: abort.signal })
      if (!abort.signal.aborted) onChange({ ...current.current, directory: data.models, editing: false, selected: current.current.selected.filter(value => data.models.includes(value)) })
    } catch (cause: any) {
      if (!abort.signal.aborted) setReadError(cause?.apiError?.code === 'MODEL_LIST_UNAUTHORIZED' ? 'hub.directory.unauthorized' : cause?.apiError?.code === 'MODEL_LIST_UNSUPPORTED' ? 'hub.directory.unsupported' : cause?.apiError?.code === 'MODEL_LIST_FAILED' ? 'hub.directory.failed' : catalogFailure(cause))
    } finally { if (request.current === abort) { request.current = null; setLoading(false) } }
  }
  const save = async () => {
    if (!canSave) return
    const nextSource = { ...source, name: sourceName(source), baseUrl: normalizedURL }
    const nextModels = catalog.models.map(model => model.candidates[0].sourceId === source.id ? { ...model, protocol: source.protocol } : model)
    for (const model of additions) nextModels.push({ id: globalThis.crypto?.randomUUID?.() || 'model-' + Math.random().toString(36).slice(2), name: model, protocol: source.protocol, strategy: 'fixed', candidates: [{ sourceId: source.id, model }] })
    if (await onSave({ ...catalog, sources: existing ? catalog.sources.map(row => row.id === source.id ? nextSource : row) : [...catalog.sources, nextSource], models: nextModels })) { message.success(t('agent.models.saved')); onBack() }
  }
  const submit = () => {
    if (!canSave) return
    if (changedConnection) modal.confirm({ className: 'tt-model-connection-confirm', title: t('hub.sourceApply'), content: t('hub.sourceImpact'), okText: t('agent.models.save'), cancelText: t('common.cancel'), onOk: save })
    else void save()
  }
  return <form className="tt-model-source-editor" onSubmit={event => { event.preventDefault(); submit() }}>
    <div className="tt-model-source-content">
      {sourceConflict && <Alert type="warning" role="alert" message={t('hub.directory.sourceChanged')} action={<Button onClick={() => onChange({ ...draft, source: { ...existing!, apiKey: '' }, original: existing!, directory: null, editing: true })}>{t('hub.directory.useLatest')}</Button>} />}
      {error && <Alert type="error" role="alert" message={t(error)} action={<Button onClick={retry}>{t('capabilities.models.reread')}</Button>} />}
      <section className="tt-model-source-connection" aria-label={t('hub.source')}>
        {draft.editing ? <>
          <label className="agent-settings-field">{t('agent.models.baseUrl')}<Input aria-label={t('agent.models.baseUrl')} type="url" value={source.baseUrl} maxLength={2000} placeholder="https://api.example.com/v1" onChange={event => updateSource({ baseUrl: event.target.value })} /></label>
          <label className="agent-settings-field">{t('agent.models.apiKey')}<Input.Password aria-label={t('agent.models.apiKey')} autoComplete="new-password" visibilityToggle={false} value={source.apiKey} maxLength={8192} placeholder={t(source.hasKey ? 'agent.models.keyKept' : 'agent.models.keyPlaceholder')} onChange={event => updateSource({ apiKey: event.target.value })} /></label>
          {needsKey && <p className="tt-model-source-warning" role="alert">{t('agent.models.newEndpointKey')}</p>}
          <details className="tt-model-source-options"><summary>{t('hub.connectionOptions')}<ChevronDown /></summary><div>
            <label className="agent-settings-field">{t('hub.directory.sourceName')}<Input aria-label={t('hub.name')} value={source.name} maxLength={100} placeholder={t('hub.directory.autoName')} onChange={event => updateSource({ name: event.target.value })} /></label>
            <label className="agent-settings-field">{t('capabilities.models.protocol')}<Select virtual={false} aria-label={t('capabilities.models.protocol')} value={source.protocol} options={modelProtocols.map(value => ({ value, label: t('capabilities.models.protocol.' + value) }))} onChange={protocol => updateSource({ protocol })} /></label>
            <label className="agent-settings-field">{t('capabilities.models.authMode')}<Select virtual={false} aria-label={t('capabilities.models.authMode')} value={source.authMode} options={['api_key', 'bearer'].map(value => ({ value, label: t('capabilities.models.auth.' + value) }))} onChange={authMode => updateSource({ authMode })} /></label>
          </div></details>
        </> : <div className="tt-model-source-summary"><LinkIcon size={18} /><div><strong>{sourceName(source)}</strong>{sourceName(source) !== source.baseUrl && <small>{source.baseUrl}</small>}</div><button type="button" className="tt-act" onClick={() => patch({ editing: true })}>{t('hub.directory.changeConnection')}</button></div>}
        <div className="tt-model-source-read"><Button type={draft.directory === null ? 'primary' : 'default'} loading={loading} disabled={!validConnection || busy} onClick={() => void read()}>{t(draft.directory === null ? 'hub.directory.fetch' : 'hub.directory.refetch')}</Button>{draft.directory === null && <span>{t('hub.directory.readHint')}</span>}</div>
        {readError && <Alert type="warning" role="alert" message={t(readError)} />}
      </section>
      {draft.directory !== null && <section className="tt-model-directory" aria-label={t('hub.directory.title')} aria-busy={loading}>
        <div className="tt-model-directory-heading"><h3>{t('hub.directory.title')}</h3>{draft.directory.length > 0 && <span role="status">{t('hub.directory.total', { count: number(draft.directory.length) })}</span>}</div>
        {!!draft.directory.length && <><Input aria-label={t('hub.directory.search')} placeholder={t('hub.directory.search')} prefix={<SearchIcon />} allowClear value={draft.query} onChange={event => patch({ query: event.target.value })} />
          <div className="tt-model-directory-selection"><Checkbox checked={!!selectable.length && selectedVisible.length === selectable.length} indeterminate={selectedVisible.length > 0 && selectedVisible.length < selectable.length} disabled={!selectable.length} onChange={event => patch({ selected: event.target.checked ? [...new Set([...draft.selected, ...selectable])] : draft.selected.filter(value => !selectable.includes(value)) })}>{t(draft.query ? 'hub.directory.selectMatches' : 'hub.directory.selectAll')}</Checkbox>{!!selected.length && <button type="button" className="tt-act" onClick={() => patch({ selected: [] })}>{t('hub.directory.clear')}</button>}</div>
        </>}
        <div className="tt-model-directory-list">{visible.map(model => <div className="tt-model-directory-row" key={model}><Checkbox checked={added.has(model) || draft.selected.includes(model)} disabled={added.has(model)} onChange={event => patch({ selected: event.target.checked ? [...draft.selected, model] : draft.selected.filter(value => value !== model) })}><span>{model}</span></Checkbox>{added.has(model) && <span className="tt-model-directory-added"><CheckIcon />{t('hub.directory.added')}</span>}</div>)}</div>
        {!visible.length && <p className="agent-settings-hint">{t(draft.directory.length ? 'hub.directory.noMatches' : 'hub.directory.empty')}</p>}
      </section>}
      <section className="tt-model-source-manual">
        <button type="button" className="tt-act" aria-expanded={draft.manualOpen} onClick={() => patch({ manualOpen: !draft.manualOpen })}><PlusIcon />{t('hub.directory.manual')}</button>
        {draft.manualOpen && <label className="agent-settings-field">{t('hub.directory.manualHint')}<Input.TextArea aria-label={t('hub.directory.manual')} rows={4} value={draft.manual} onChange={event => patch({ manual: event.target.value })} />{invalidManual && <span className="tt-model-source-warning" role="alert">{t('hub.directory.invalidManual')}</span>}</label>}
      </section>
      {overLimit && <Alert type="warning" role="alert" message={t('hub.directory.limit')} />}
      {!!attached.length && <p className="agent-settings-hint">{t('hub.directory.kept', { count: number(attached.length) })}</p>}
    </div>
    <footer className="tt-model-source-footer"><span role="status">{t(additions.length ? 'hub.directory.selected' : 'hub.directory.choose', { count: number(additions.length) })}</span><Button type="primary" htmlType="submit" loading={busy} disabled={!canSave}>{t(additions.length ? 'hub.directory.saveModels' : 'agent.models.save', { count: number(additions.length) })}</Button></footer>
  </form>
}
