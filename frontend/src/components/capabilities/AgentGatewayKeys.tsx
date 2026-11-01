import { useEffect, useState } from 'react'
import { Alert, App, Button, Input, Modal, Popconfirm, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'

import { gatewayAgentNames, type GatewayAgentKey } from './gateway-agent'
type KeyList = { revision: string; keys: GatewayAgentKey[] }
export default function AgentGatewayKeys({ onUsage, onChanged }: { onUsage: (kind: string) => void; onChanged?: () => void }) {
  const { t } = useI18n(), { message } = App.useApp()
  const [value, setValue] = useState<KeyList | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(''), [version, setVersion] = useState(0)
  const [issued, setIssued] = useState<{ kind: string; key: string } | null>(null)
  useEffect(() => {
    const abort = new AbortController()
    setError('')
    void api('GET', '/agent/model-gateway/keys', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) setValue(data) }).catch(() => { if (!abort.signal.aborted) setError('hub.keys.failed') })
    return () => abort.abort()
  }, [version])
  const mutate = async (row: GatewayAgentKey, action: 'rotate' | 'disable') => {
    if (busy || !value) return
    setBusy(row.agentKind); setError('')
    try {
      const { data, key } = await api('POST', `/agent/model-gateway/keys/${row.agentKind}/${action}`, { revision: value.revision, configRevision: row.configRevision })
      setValue(data); onChanged?.()
      if (key) setIssued({ kind: row.agentKind, key })
      message.success(t(action === 'rotate' ? 'hub.keys.rotated' : 'hub.keys.disabledMessage'))
      window.dispatchEvent(new Event('roam:agent-models-changed'))
    } catch (cause) {
      const code = (cause as { apiError?: { code?: string } })?.apiError?.code
      setError(['MODEL_CATALOG_CHANGED', 'AGENT_CONFIG_CHANGED'].includes(code || '') ? 'hub.error.changed' : 'hub.keys.failed')
    } finally { setBusy('') }
  }
  return <section className="tt-agent-gateway-keys">
    <p className="agent-settings-hint">{t('hub.keys.hint')}</p>
    {error && <Alert type="error" role="alert" message={t(error)} action={<Button disabled={!!busy} onClick={() => setVersion(value => value + 1)}>{t('capabilities.models.reread')}</Button>} />}
    {!value && !error && <Spin />}
    {value?.keys.map(row => <article className="tt-agent-gateway-key" key={row.agentKind} aria-label={(gatewayAgentNames[row.agentKind] || row.agentKind)}>
      <div><strong>{(gatewayAgentNames[row.agentKind] || row.agentKind)}</strong><span>{t(row.disabled ? 'hub.keys.disabled' : row.pending ? 'hub.keys.pending' : row.unavailable ? 'hub.keys.unavailable' : row.configChanged ? 'hub.keys.changed' : row.connected ? 'hub.keys.connected' : 'hub.keys.ready')}</span><code>{t('hub.keys.suffix', { suffix: row.suffix })}</code></div>
      <div className="tt-model-hub-actions">
        <Button onClick={() => onUsage(row.agentKind)}>{t('hub.keys.usage')}</Button>
        <Popconfirm classNames={{ root: 'tt-model-connection-confirm' }} title={t(row.disabled ? 'hub.keys.enableConfirm' : 'hub.keys.rotateConfirm')} description={t(row.connected ? 'hub.keys.rotateScope' : 'hub.keys.rotateManual')} onConfirm={() => mutate(row, 'rotate')} okText={t('hub.keys.rotate')} cancelText={t('common.cancel')}><Button loading={busy === row.agentKind} disabled={!!busy || row.unavailable || row.configChanged}>{t(row.disabled ? 'hub.keys.enable' : row.pending ? 'agent.retry' : 'hub.keys.rotate')}</Button></Popconfirm>
        {!row.disabled && <Popconfirm classNames={{ root: 'tt-model-connection-confirm' }} title={t('hub.keys.disableConfirm')} description={t('hub.keys.disableScope')} onConfirm={() => mutate(row, 'disable')} okText={t('hub.keys.disable')} cancelText={t('common.cancel')}><Button danger disabled={!!busy}>{t('hub.keys.disable')}</Button></Popconfirm>}
      </div>
    </article>)}
    {issued && <Modal className="tt-model-key-issued" open title={t('hub.keys.issued', { agent: issued ? gatewayAgentNames[issued.kind] : '' })} onCancel={() => setIssued(null)} footer={<Button type="primary" onClick={() => setIssued(null)}>{t('common.close')}</Button>}>
      <p>{t('hub.keys.once')}</p><Button onClick={async () => { try { await navigator.clipboard.writeText(issued?.key || ''); message.success(t('common.copied')) } catch { message.error(t('hub.keys.copyFailed')) } }}>{t('common.copy')}</Button><Input.TextArea aria-label={t('hub.keys.secret')} readOnly autoSize value={issued?.key || ''} />
    </Modal>}
  </section>
}
