import { App } from 'antd'
import { Alert, Button, Input, Spin } from './model-controls'
import { useI18n } from '../../i18n'
import { useGatewayFixedKey, type GatewayFixedKeyController } from './gateway-fixed-key'

export default function GatewayAccessKey({ onChanged, value: key, onChange: setKey, controller, onCancel, onSaved }: { onChanged: () => void; value: string; onChange: (value: string) => void; controller?: GatewayFixedKeyController; onCancel?: () => void; onSaved?: () => void }) {
  const { t } = useI18n(), { message, modal } = App.useApp()
  const local = useGatewayFixedKey(!controller), state = controller || local
  const { view, error, busy, loading } = state
  const valid = /^[\x21-\x7e]{16,512}$/.test(key)
  const save = async (disable = false) => {
    if (!disable && !valid) return false
    if (!await state.save(disable ? undefined : key)) return false
    if (!disable) setKey('')
    onChanged(); onSaved?.(); message.success(t(disable ? 'hub.gateway.keyDisabled' : 'hub.gateway.keySaved')); return true
  }
  const replace = () => {
    if (!view?.hasKey) { void save(); return }
    modal.confirm({ className: 'tt-gateway-key-dialog', title: t('gatewayWorkspace.replaceFixed'), content: t('gatewayWorkspace.replaceHint'), okText: t('settings.save'), cancelText: t('common.cancel'), onOk: async () => { if (!await save()) throw new Error('save failed') } })
  }
  return <form className="tt-gateway-key-form" onSubmit={event => { event.preventDefault(); replace() }}>
    <div className="tt-gateway-editor-scroll">
      {error && <Alert message={t(error)} action={<Button disabled={busy || loading} onClick={state.retry}>{t('capabilities.models.reread')}</Button>} />}
      {!view ? !error && <Spin /> : <>
        <p className="agent-settings-hint">{t('gatewayWorkspace.fixedHint')}</p>
        <label className="agent-settings-field"><span>{t('hub.gateway.key')}</span><Input.Password aria-label={t('hub.gateway.key')} value={key} autoComplete="new-password" maxLength={512} disabled={busy || loading} placeholder={t('gatewayWorkspace.fixedPlaceholder')} onChange={event => setKey(event.target.value)} aria-invalid={!!key && !valid} aria-describedby={key && !valid ? 'gateway-fixed-error' : undefined} /></label>
        {view.hasKey && <><p role="status" className="agent-settings-hint">{t('hub.gateway.keyConfigured', { suffix: view.suffix })}</p><p className="tt-gateway-warning">{t('gatewayWorkspace.replaceHint')}</p></>}
        {!!key && !valid && <p id="gateway-fixed-error" role="alert" className="agent-settings-error">{t('hub.gateway.invalidKey')}</p>}
      </>}
    </div>
    <footer className="tt-gateway-editor-footer">
      {view?.hasKey && <Button disabled={busy || loading} className="tt-gateway-danger" onClick={() => modal.confirm({ className: 'tt-gateway-key-dialog', title: t('hub.gateway.disableKey'), content: t('hub.gateway.disableHint'), okText: t('hub.gateway.disableKey'), cancelText: t('common.cancel'), onOk: async () => { if (!await save(true)) throw new Error('save failed') } })}>{t('hub.gateway.disableKey')}</Button>}
      {onCancel && <Button disabled={busy} onClick={onCancel}>{t('common.cancel')}</Button>}
      <Button type="primary" htmlType="submit" loading={busy} disabled={!view || !valid || loading}>{t('settings.save')}</Button>
    </footer>
  </form>
}
