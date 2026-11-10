import { useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Checkbox, Input, Select, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { pluginFailure, type PluginProvider } from './MagpiePluginImport'

type Prompt = { key: string; message: string; type: string; placeholder?: string; options?: { label: string; value: string }[] }
type SignIn = { session: string; url: string; instructions: string; method: string }
export default function MagpieSourceSettings({ sourceId, onChanged }: { sourceId: string; onChanged: () => void }) {
  const { t, locale } = useI18n(), { message } = App.useApp()
  const path = '/agent/model-gateway/plugins/sources/' + sourceId
  const fresh = useRef(false)
  const [info, setInfo] = useState<{ provider: PluginProvider; options: Record<string, boolean>; desktopUnavailable: boolean; desktopAppMissing?: boolean } | null>(null)
  const [version, setVersion] = useState(0), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [method, setMethod] = useState(0), [key, setKey] = useState(''), [code, setCode] = useState(''), [signIn, setSignIn] = useState<SignIn | null>(null), [job, setJob] = useState('')
  const [prompt, setPrompt] = useState<Prompt | null>(null), [inputs, setInputs] = useState<Record<string, string>>({}), [answer, setAnswer] = useState('')
  const reload = () => { setVersion(previous => previous + 1); onChanged() }
  useEffect(() => {
    const abort = new AbortController()
    const query = fresh.current ? '?refresh=1' : ''; fresh.current = false
    void api('GET', path + '/info' + query, undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) { setInfo(data); setError('') } }).catch(cause => { if (!abort.signal.aborted) setError(pluginFailure(cause)) })
    return () => abort.abort()
  }, [path, version])
  useEffect(() => {
    if (!job) return
    const abort = new AbortController(); let timer: ReturnType<typeof setTimeout>, delay = 1000
    const read = async () => {
      if (abort.signal.aborted) return
      if (document.visibilityState === 'hidden') { timer = setTimeout(read, 1000); return }
      try {
        const { data } = await api('GET', path + '/auth-jobs/' + job, undefined, { signal: abort.signal })
        if (abort.signal.aborted) return
        if (data.done) { setJob(''); setSignIn(null); if (data.ok) { setKey(''); message.success(t('hub.plugin.signedIn')); reload() } else setError('hub.plugin.signInFailed'); return }
        delay = 1000
      } catch (cause) { if (abort.signal.aborted) return; setError(pluginFailure(cause)); delay = Math.min(delay * 2, 30000) }
      timer = setTimeout(read, delay)
    }
    timer = setTimeout(read, delay)
    return () => { abort.abort(); clearTimeout(timer); void api('DELETE', path + '/auth-jobs/' + job).catch(() => {}) }
  }, [job, path])
  const callback = async (flow: SignIn) => {
    const { data } = await api('POST', path + '/auth', { action: 'callback', session: flow.session, code })
    setJob(data.jobId)
  }
  const login = async () => {
    if (busy || job || !info) return
    setBusy(true); setError('')
    try {
      let next = inputs
      if (prompt) {
        const { data } = await api('POST', path + '/auth', { action: 'validate', method, key: prompt.key, value: answer })
        if (data.invalid) { setError('hub.plugin.invalidAnswer'); return }
        next = { ...inputs, [prompt.key]: answer }; setInputs(next)
      }
      const { data: question } = await api('POST', path + '/auth', { action: 'prompt', method, inputs: next })
      if (question.prompt) { setPrompt(question.prompt); setAnswer(''); return }
      setPrompt(null)
      const selected = info.provider.methods[method]
      const { data } = await api('POST', path + '/auth', { action: selected.type === 'api' ? 'apiKey' : 'authorize', method, key, inputs: next })
      if (!data.ok) { setError('hub.plugin.signInFailed'); return }
      if (selected.type === 'api') { setKey(''); setInputs({}); reload(); message.success(t('hub.plugin.signedIn')) }
      else { const flow = data as SignIn; setSignIn(flow); if (flow.method === 'auto') await callback(flow) }
    } catch (cause) { setError(pluginFailure(cause)) }
    finally { setBusy(false) }
  }
  const option = async (name: string, enabled: boolean) => {
    if (!info || busy) return
    setBusy(true); setError('')
    const options = { ...info.options, [name]: enabled }
    try { await api('POST', path + '/options', { options }); setInfo({ ...info, options }); reload() }
    catch (cause) { setError(pluginFailure(cause)) }
    finally { setBusy(false) }
  }
  let loginURL = ''
  try { if (signIn?.url && new URL(signIn.url).protocol === 'https:') loginURL = signIn.url } catch { /* Only browser URLs may be opened. */ }
  return <section className="tt-model-plugin-settings" aria-label={t('hub.plugin.settings')}>
    {error && <Alert type="error" role="alert" message={t(error)} action={<Button disabled={busy || !!job} onClick={() => { fresh.current = true; setVersion(previous => previous + 1) }}>{t('capabilities.models.reread')}</Button>} />}
    {!info ? !error && <Spin /> : <>
      {info.provider.fellBack && <Alert type="warning" message={t('hub.plugin.refreshRequired')} />}
      {info.desktopUnavailable && <Alert type="warning" message={t('hub.plugin.desktopUnavailable')} />}
      {info.desktopAppMissing && <Alert type="warning" message={t('hub.plugin.desktopMissing')} />}
      <p role="status">{t(info.provider.signedIn ? 'hub.plugin.signedIn' : 'hub.plugin.notSignedIn')}</p>
      <label className="agent-settings-field">{t('hub.plugin.loginMethod')}<Select virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('hub.plugin.loginMethod')} value={method} disabled={busy || !!job} options={info.provider.methods.map((row, index) => ({ value: index, label: row.labels?.[locale] || row.labels?.[locale.startsWith('zh') ? 'zh' : 'en'] || row.labels?.[locale.startsWith('zh') ? 'zh' : 'en'] || row.label }))} onChange={value => { setMethod(value); setPrompt(null); setInputs({}); setSignIn(null); setKey(''); setCode('') }} /></label>
      {info.provider.methods[method]?.type === 'api' && !info.provider.methods[method].keyless && <label className="agent-settings-field">{t('agent.models.apiKey')}<Input.Password aria-label={t('agent.models.apiKey')} autoComplete="new-password" value={key} visibilityToggle={false} onChange={event => setKey(event.target.value)} /></label>}
      {prompt && <label className="agent-settings-field">{prompt.message}{prompt.type === 'select' ? <Select virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={prompt.message} value={answer || undefined} options={prompt.options} onChange={setAnswer} /> : <Input aria-label={prompt.message} placeholder={prompt.placeholder} value={answer} onChange={event => setAnswer(event.target.value)} />}</label>}
      {!signIn && <Button type="primary" disabled={busy || info.desktopUnavailable || info.desktopAppMissing || (!prompt && info.provider.methods[method]?.type === 'api' && !info.provider.methods[method]?.keyless && !key.trim())} loading={busy} onClick={() => void login()}>{t(prompt ? 'hub.plugin.next' : 'hub.plugin.signIn')}</Button>}
      {signIn && <div className="tt-model-plugin-signin">{signIn.instructions && <p>{signIn.instructions}</p>}{loginURL && <a href={loginURL} target="_blank" rel="noreferrer">{t('hub.plugin.openLogin')}</a>}{signIn.method === 'code' && <><Input aria-label={t('hub.plugin.loginCode')} value={code} onChange={event => setCode(event.target.value)} /><Button disabled={!code || !!job} onClick={() => void callback(signIn).catch(cause => setError(pluginFailure(cause)))}>{t('hub.plugin.finishLogin')}</Button></>}{job && <Spin />}<Button onClick={() => { setJob(''); setSignIn(null); setCode('') }}>{t('common.cancel')}</Button></div>}
      {info.provider.options?.length > 0 && <div className="tt-model-plugin-options">{info.provider.options.map(row => <Checkbox key={row.key} disabled={busy || !!job} checked={info.options?.[row.key] ?? row.default} onChange={event => void option(row.key, event.target.checked)}>{row.labels?.[locale] || row.labels?.[locale.startsWith('zh') ? 'zh' : 'en'] || row.label}</Checkbox>)}</div>}
    </>}
  </section>
}
