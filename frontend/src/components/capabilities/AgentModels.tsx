import { useEffect, useRef, useState } from 'react'
import { Alert, AutoComplete, Button, Empty, Input, Popconfirm, Select, Spin, message } from 'antd'
import { type AgentKind } from '../../agent-kind'
import { agentModels, agentModelOptions, applyAgentModel, deleteAgentModel, restoreAgentModel, saveAgentModel, type AgentModelInput, type AgentModelProfile, type AgentModelView } from '../../agent-registry'
import { useI18n } from '../../i18n'
import { ChevronDown, PlusIcon } from '../../icons'
import { useLayout } from '../../layout'

const protocolChoices = (kind: AgentKind) => kind === 'claude' ? ['anthropic-messages'] : kind === 'codex' ? ['openai-responses'] : ['openai-completions', 'openai-responses', 'anthropic-messages']
const newDraft = (kind: AgentKind): AgentModelInput => ({ name: '', baseUrl: '', model: '', protocol: protocolChoices(kind)[0], authMode: 'api_key', apiKey: '', keyEnv: '', reasoningEffort: '' })
const errors: Record<string, string> = {
  INVALID_MODEL_PROFILE: 'invalid', INVALID_MODEL_PROTOCOL: 'invalidProtocol', INVALID_MODEL_KEY: 'invalidKey', MODEL_KEY_ENV_MISSING: 'missingEnv',
  MODEL_LIST_UNAUTHORIZED: 'modelAuth', MODEL_LIST_UNSUPPORTED: 'modelUnsupported', MODEL_LIST_FAILED: 'modelFetch',
  MODEL_PROFILE_NAME_EXISTS: 'duplicate', MODEL_PROFILE_LIMIT: 'limit', MODEL_PROFILE_ACTIVE: 'activeDelete', MODEL_PROFILE_NOT_FOUND: 'notFound',
  AGENT_CONFIG_CHANGED: 'changed', AGENT_CONFIG_INVALID: 'invalidConfig', AGENT_CONFIG_PATH_INVALID: 'invalidPath', AGENT_CONFIG_INLINE_OVERRIDE: 'inlineOverride',
  AGENT_CONFIG_READ_FAILED: 'readFailed', AGENT_CONFIG_WRITE_FAILED: 'writeFailed', AGENT_CONFIG_RECOVERY_REQUIRED: 'recovery',
  AGENT_CONFIG_RESTORE_UNAVAILABLE: 'restoreUnavailable', OPENCODE_CONFIG_VERSION_UNKNOWN: 'unknownVersion', MODEL_STORE_TOO_LARGE: 'limit', AGENT_CONFIG_TOO_LARGE: 'limit',
}

export default function AgentModels({ kind }: { kind: AgentKind }) {
  const { t } = useI18n()
  const layout = useLayout()
  const scroll = useRef<HTMLDivElement>(null)
  const revealField = (field: HTMLElement) => {
    const pane = scroll.current
    if (!pane?.contains(field)) return
    const input = field.getBoundingClientRect(), bounds = pane.getBoundingClientRect()
    pane.scrollTop += input.bottom + input.height / 2 - bounds.bottom
  }
  useEffect(() => {
    if (!layout.phone || !layout.keyboard) return
    const frame = requestAnimationFrame(() => { if (document.activeElement instanceof HTMLElement) revealField(document.activeElement) })
    return () => cancelAnimationFrame(frame)
  }, [layout.phone, layout.keyboard])
  const [view, setView] = useState<AgentModelView | null>(null)
  const [editing, setEditing] = useState<AgentModelProfile | 'new' | null>(null)
  const [draft, setDraft] = useState<AgentModelInput>(() => newDraft(kind))
  const [credential, setCredential] = useState<'key' | 'env'>('key')
  const [busy, setBusy] = useState(''), [error, setError] = useState('')
  const live = useRef(true)
  const [remoteModels, setRemoteModels] = useState<{ connection: string; models: string[] } | null>(null)
  const [modelBusy, setModelBusy] = useState(false), [modelError, setModelError] = useState('')
  const [modelSearch, setModelSearch] = useState('')
  const modelRequest = useRef<AbortController | null>(null)
  const connection = JSON.stringify([kind, editing === 'new' ? '' : editing?.id, draft.baseUrl, draft.protocol, draft.authMode, credential,
    credential === 'env' ? draft.keyEnv : draft.apiKey])
  useEffect(() => {
    modelRequest.current?.abort(); modelRequest.current = null
    setModelBusy(false); setModelError('')
    return () => { modelRequest.current?.abort() }
  }, [connection])
  const modelOptions = [...new Set([
    ...(view?.profiles.filter(p => p.baseUrl.replace(/\/$/, '') === draft.baseUrl.trim().replace(/\/$/, '') && p.protocol === draft.protocol).map(p => p.model) || []),
    ...(remoteModels?.connection === connection ? remoteModels.models : []),
  ])].map(value => ({ value }))
  const errorText = (cause: unknown) => {
    const code = (cause as { apiError?: { code?: string }; message?: string })?.apiError?.code || (cause as Error)?.message || ''
    return t('capabilities.models.error.' + (errors[code] || 'failed'))
  }
  useEffect(() => {
    live.current = true
    const controller = new AbortController()
    void agentModels(kind, controller.signal).then(result => { if (live.current) setView(result) }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)) })
    return () => { live.current = false; controller.abort() }
  }, [kind])
  const fetchModels = async () => {
    modelRequest.current?.abort()
    const controller = new AbortController(); modelRequest.current = controller
    setModelBusy(true); setModelError('')
    try {
      const models = await agentModelOptions(kind, { ...draft, profileId: editing && editing !== 'new' ? editing.id : undefined,
        keyEnv: credential === 'env' ? draft.keyEnv : '', apiKey: credential === 'key' ? draft.apiKey : '' }, controller.signal)
      if (!live.current || controller.signal.aborted) return
      setRemoteModels({ connection, models })
      if (!models.length) setModelError(t('capabilities.models.noModels'))
      else message.success(t('capabilities.models.modelsLoaded'))
    } catch (cause) {
      if (live.current && !controller.signal.aborted) setModelError(errorText(cause))
    } finally { if (live.current && modelRequest.current === controller) setModelBusy(false) }
  }
  const reload = async () => {
    if (busy) return
    setBusy('load'); setError('')
    try { const result = await agentModels(kind); if (live.current) setView(result) }
    catch (cause) { if (live.current) setError(errorText(cause)) }
    finally { if (live.current) setBusy('') }
  }
  const edit = (profile?: AgentModelProfile) => {
    setEditing(profile || 'new'); setError('')
    setDraft(profile ? { name: profile.name, baseUrl: profile.baseUrl, model: profile.model, protocol: profile.protocol, authMode: profile.authMode, apiKey: '', keyEnv: profile.keyEnv || '', reasoningEffort: profile.reasoningEffort || '' } : newDraft(kind))
    setCredential(profile?.keyEnv ? 'env' : 'key')
  }
  const save = async () => {
    if (busy || !editing) return
    setBusy('save'); setError('')
    const input = { ...draft, keyEnv: credential === 'env' ? draft.keyEnv : '', apiKey: credential === 'key' ? draft.apiKey : '' }
    try {
      const profile = await saveAgentModel(kind, editing === 'new' ? undefined : editing.id, input)
      if (!live.current) return
      setView(previous => previous ? { ...previous, profiles: [...previous.profiles.filter(p => p.id !== profile.id), profile] } : previous)
      setEditing(null); setDraft(newDraft(kind)); message.success(t('capabilities.models.saved'))
      const next = await agentModels(kind)
      if (live.current) setView(next)
    } catch (cause) { if (live.current) setError(errorText(cause)) }
    finally { if (live.current) setBusy('') }
  }
  const apply = async (profile?: AgentModelProfile) => {
    if (busy || !view) return
    setBusy(profile ? 'apply:' + profile.id : 'restore'); setError('')
    try {
      const result = profile ? await applyAgentModel(kind, profile.id, view.revision) : await restoreAgentModel(kind, view.revision)
      if (live.current) {
        setView(result); message.success(t(profile ? 'capabilities.models.appliedMessage' : 'capabilities.models.restored'))
        window.dispatchEvent(new Event('roam:agent-models-changed'))
      }
    } catch (cause) { if (live.current) setError(errorText(cause)) }
    finally { if (live.current) setBusy('') }
  }
  const remove = async (profile: AgentModelProfile) => {
    if (busy) return
    setBusy('delete:' + profile.id); setError('')
    try {
      await deleteAgentModel(kind, profile.id)
      if (live.current) setView(previous => previous ? { ...previous, profiles: previous.profiles.filter(p => p.id !== profile.id) } : previous)
    } catch (cause) { if (live.current) setError(errorText(cause)) }
    finally { if (live.current) setBusy('') }
  }
  const field = (name: 'name' | 'baseUrl' | 'model' | 'keyEnv', label: string, placeholder?: string) => <label>{t(label)}<Input
    aria-label={t(label)} value={draft[name]} placeholder={placeholder ? t(placeholder) : undefined} disabled={!!busy} autoComplete="off"
    onChange={event => setDraft(previous => ({ ...previous, [name]: event.target.value }))} /></label>
  return <div className="tt-agent-models">
    <div className="tt-agent-model-scroll" ref={scroll}>
      {error && <Alert type="error" showIcon message={error} action={<Button disabled={!!busy} loading={busy === 'load'} onClick={() => { void reload() }}>{t('capabilities.models.reread')}</Button>} />}
      {!view && !error && <Spin />}
      {editing ? <form id="agent-model-editor" className="tt-agent-model-form" onFocusCapture={event => { const field = event.target; if (layout.phone && field instanceof HTMLInputElement) requestAnimationFrame(() => revealField(field)) }} onSubmit={event => { event.preventDefault(); void save() }}>
        <h3>{t(editing === 'new' ? 'capabilities.models.add' : 'capabilities.models.edit')}</h3>
        {field('name', 'capabilities.models.name')}
        {field('baseUrl', 'capabilities.models.baseUrl', 'capabilities.models.baseUrlPlaceholder')}
        <label>{t('capabilities.models.protocol')}<Select aria-label={t('capabilities.models.protocol')} value={draft.protocol} disabled={!!busy}
          options={protocolChoices(kind).map(value => ({ value, label: t('capabilities.models.protocol.' + value) }))} onChange={protocol => setDraft(previous => ({ ...previous, protocol }))} /></label>
        <div className="tt-agent-model-field"><label htmlFor="professional-agent-model">{t('capabilities.models.model')}</label>
          <div className="tt-agent-model-picker"><AutoComplete id="professional-agent-model" classNames={{ popup: { root: 'tt-agent-model-options' } }} placement={layout.phone ? 'topLeft' : 'bottomLeft'} getPopupContainer={trigger => trigger.parentElement!} value={draft.model} options={modelOptions} disabled={!!busy}
            filterOption={(_, option) => String(option?.value || '').toLowerCase().includes(modelSearch.toLowerCase())}
            onFocus={() => setModelSearch('')} onSearch={setModelSearch} onSelect={() => setModelSearch('')}
            onChange={model => setDraft(previous => ({ ...previous, model }))}>
            <Input aria-label={t('capabilities.models.model')} autoComplete="off"
              placeholder={t('capabilities.models.chooseModel')} suffix={<ChevronDown size={16} />} />
          </AutoComplete><Button loading={modelBusy} disabled={!!busy || !draft.baseUrl.trim()} onClick={() => { void fetchModels() }}>{t('capabilities.models.fetchModels')}</Button></div>
          {modelError && <p className="tt-agent-model-fetch-error" role="status">{modelError}</p>}
        </div>
        {kind === 'codex' && <label>{t('capabilities.models.reasoning')}<Select aria-label={t('capabilities.models.reasoning')} value={draft.reasoningEffort || ''} disabled={!!busy}
          options={['', 'low', 'medium', 'high', 'xhigh'].map(value => ({ value, label: t('capabilities.models.reasoning.' + (value || 'default')) }))} onChange={reasoningEffort => setDraft(previous => ({ ...previous, reasoningEffort }))} /></label>}
        {kind === 'claude' && <label>{t('capabilities.models.authMode')}<Select aria-label={t('capabilities.models.authMode')} value={draft.authMode} disabled={!!busy}
          options={['api_key', 'bearer'].map(value => ({ value, label: t('capabilities.models.auth.' + value) }))} onChange={authMode => setDraft(previous => ({ ...previous, authMode }))} /></label>}
        <label>{t('capabilities.models.credential')}<Select aria-label={t('capabilities.models.credential')} value={credential} disabled={!!busy}
          options={['key', 'env'].map(value => ({ value, label: t('capabilities.models.credential.' + value) }))} onChange={setCredential} /></label>
        {credential === 'env' ? field('keyEnv', 'capabilities.models.keyEnv', 'capabilities.models.keyEnvPlaceholder') : <label>{t('capabilities.models.apiKey')}<Input.Password
          aria-label={t('capabilities.models.apiKey')} value={draft.apiKey} disabled={!!busy} autoComplete="new-password"
          placeholder={t(editing !== 'new' && editing.hasKey ? 'capabilities.models.keySaved' : 'capabilities.models.keyPlaceholder')}
          onChange={event => setDraft(previous => ({ ...previous, apiKey: event.target.value }))} /></label>}
        <p>{t('capabilities.models.saveHint')}</p>
      </form> : view && <>
        <div className="tt-agent-model-toolbar"><div className="tt-agent-model-current"><span>{t('capabilities.models.current')}</span>
          <strong>{[view.current.provider, view.current.model].filter(Boolean).join(' / ') || t('capabilities.models.toolDefault')}</strong></div>
          <Button icon={<PlusIcon size={16} />} disabled={!!busy} onClick={() => edit()}>{t('capabilities.models.add')}</Button></div>
        {view.changed && <Alert type="warning" showIcon message={t('capabilities.models.externalChange')} />}
        {!view.profiles.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('capabilities.models.empty')} />}
        <div className="tt-agent-model-list">{view.profiles.map(profile => <article className="tt-agent-model-row" key={profile.id} aria-label={profile.name}>
          <div className="tt-agent-model-heading"><strong>{profile.name}</strong>{profile.applied ? <span className="tt-agent-model-applied">{t('capabilities.models.applied')}</span>
            : view.activeId === profile.id && <span>{t('capabilities.models.pending')}</span>}</div>
          <span>{profile.model}</span><span className="tt-agent-model-endpoint">{profile.baseUrl}</span>
          <div className="tt-agent-model-row-actions"><Popconfirm title={t('capabilities.models.applyConfirm')} onConfirm={() => apply(profile)} okText={t('capabilities.models.apply')} cancelText={t('common.cancel')}>
            <Button disabled={!!busy || profile.applied} loading={busy === 'apply:' + profile.id}>{t('capabilities.models.apply')}</Button></Popconfirm>
            <button type="button" className="tt-act" disabled={!!busy} onClick={() => edit(profile)}>{t('capabilities.models.editAction')}</button>
            <Popconfirm title={t('capabilities.models.deleteConfirm')} onConfirm={() => remove(profile)} okText={t('capabilities.models.deleteAction')} cancelText={t('common.cancel')}>
              <button type="button" className="tt-act danger" disabled={!!busy || view.activeId === profile.id}>{t('capabilities.models.deleteAction')}</button></Popconfirm></div>
        </article>)}</div>
        <p>{t('capabilities.models.effectHint')}</p>
        <details className="tt-agent-model-paths"><summary>{t('capabilities.models.configFiles')}</summary>{view.configPaths.map(path => <code key={path}>{path}</code>)}</details>
      </>}
    </div>
    <div className="tt-agent-model-actions">{editing ? <>
      <Button disabled={!!busy} onClick={() => { setEditing(null); setDraft(newDraft(kind)); setError('') }}>{t('common.cancel')}</Button>
      <Button type="primary" htmlType="submit" form="agent-model-editor" loading={busy === 'save'} disabled={!!busy || !draft.name.trim() || !draft.baseUrl.trim() || !draft.model.trim()}>{t('capabilities.models.save')}</Button>
    </> : view?.canRestore && <Popconfirm title={t('capabilities.models.restoreConfirm')} onConfirm={() => apply()} okText={t('capabilities.models.restore')} cancelText={t('common.cancel')}>
      <Button disabled={!!busy} loading={busy === 'restore'}>{t('capabilities.models.restore')}</Button></Popconfirm>}</div>
  </div>
}
