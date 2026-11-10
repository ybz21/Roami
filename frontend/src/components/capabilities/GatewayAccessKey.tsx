import { useEffect, useState } from 'react'
import { Alert, App, Button, Input, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { catalogFailure } from './model-hub-api'

type AccessKeyView = { revision: string; hasKey: boolean; suffix: string }
const failure = (cause: any) => cause?.apiError?.code === 'INVALID_MODEL_GATEWAY_KEY' ? 'hub.gateway.invalidKey' : catalogFailure(cause)

export default function GatewayAccessKey({ onChanged, value: key, onChange: setKey }: { onChanged: () => void; value: string; onChange: (value: string) => void }) {
  const { t } = useI18n(), { message, modal } = App.useApp()
  const [view, setView] = useState<AccessKeyView | null>(null)
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [version, setVersion] = useState(0)
  useEffect(() => {
    const abort = new AbortController()
    setError('')
    void api('GET', '/agent/model-gateway/access-key', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) setView(data) }).catch(cause => { if (!abort.signal.aborted) setError(failure(cause)) })
    return () => abort.abort()
  }, [version])
  const valid = /^[\x21-\x7e]{16,512}$/.test(key)
  const save = async (disable = false) => {
    if (!view || busy || !disable && !valid) return
    setBusy(true); setError('')
    try {
      const { data } = await api(disable ? 'DELETE' : 'PUT', '/agent/model-gateway/access-key', { revision: view.revision, ...(disable ? {} : { apiKey: key }) })
      setView(data); if (!disable) setKey(''); onChanged(); message.success(t(disable ? 'hub.gateway.keyDisabled' : 'hub.gateway.keySaved'))
    } catch (cause) { setError(failure(cause)) }
    finally { setBusy(false) }
  }
  return <form className="agent-settings-form" onSubmit={event => { event.preventDefault(); void save() }}>
    {error && <Alert type="error" role="alert" message={t(error)} action={<Button disabled={busy} onClick={() => setVersion(value => value + 1)}>{t('capabilities.models.reread')}</Button>} />}
    {!view ? !error && <Spin /> : <>
      <label className="agent-settings-field">{t('hub.gateway.key')}<Input.Password aria-label={t('hub.gateway.key')} value={key} autoComplete="new-password" visibilityToggle={false} maxLength={512} disabled={busy} placeholder={t(view.hasKey ? 'agent.models.keyKept' : 'agent.models.keyPlaceholder')} onChange={event => setKey(event.target.value)} /></label>
      <p className="agent-settings-hint">{t('hub.gateway.keyHint')}</p>
      {view.hasKey && <p role="status" className="agent-settings-hint">{t('hub.gateway.keyConfigured', { suffix: view.suffix })}</p>}
      {!!key && !valid && <p role="alert" className="agent-settings-error">{t('hub.gateway.invalidKey')}</p>}
      <div className="agent-settings-save">
        {view.hasKey && <Button danger disabled={busy} onClick={() => modal.confirm({ title: t('hub.gateway.disableKey'), content: t('hub.gateway.disableHint'), okText: t('hub.gateway.disableKey'), cancelText: t('common.cancel'), onOk: () => save(true) })}>{t('hub.gateway.disableKey')}</Button>}
        <Button type="primary" htmlType="submit" loading={busy} disabled={!valid || busy}>{t('settings.save')}</Button>
      </div>
    </>}
  </form>
}
