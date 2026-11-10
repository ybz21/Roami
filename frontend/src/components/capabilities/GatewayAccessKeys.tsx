import { useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Input, Modal, Spin, Tag } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { CopyIcon, PlusIcon } from '../../icons'
import { catalogFailure } from './model-hub-api'
import GatewayAccessKey from './GatewayAccessKey'

type KeyRow = { id: string; name: string; suffix: string; disabled: boolean }
type KeyView = { revision: string; keys: KeyRow[]; apiKey?: string }
const path = '/agent/model-gateway/access-keys'
export default function GatewayAccessKeys({ onChanged, value, onChange }: { onChanged: () => void; value: string; onChange: (value: string) => void }) {
  const { t } = useI18n(), { message, modal } = App.useApp()
  const [view, setView] = useState<KeyView | null>(null), [name, setName] = useState('')
  const viewRef = useRef<KeyView | null>(null), writing = useRef(false)
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [version, setVersion] = useState(0), [issued, setIssued] = useState('')
  useEffect(() => {
    const abort = new AbortController()
    void api('GET', path, undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) { viewRef.current = data; setView(data); setError('') } }).catch(cause => { if (!abort.signal.aborted) setError(catalogFailure(cause)) })
    return () => abort.abort()
  }, [version])
  const change = async (method: string, suffix = '', fields: Record<string, unknown> = {}) => {
    if (!viewRef.current || writing.current) return false
    writing.current = true; setBusy(true); setError('')
    try {
      const { data } = await api(method, path + suffix, { revision: viewRef.current.revision, ...fields })
      const { apiKey, ...metadata } = data as KeyView
      viewRef.current = metadata; setView(metadata); if (apiKey) setIssued(apiKey)
      if (method === 'POST' && !suffix) setName('')
      onChanged(); return true
    } catch (cause) { setError(catalogFailure(cause)); return false }
    finally { writing.current = false; setBusy(false) }
  }
  const confirm = (row: KeyRow, action: 'rotate' | 'delete' | 'disable') => modal.confirm({
    title: t(`hub.gateway.${action}Key`), content: t(`hub.gateway.${action}Hint`), okText: t(`hub.gateway.${action}Key`), cancelText: t('common.cancel'),
    onOk: async () => { if (!await change(action === 'rotate' ? 'POST' : action === 'delete' ? 'DELETE' : 'PATCH', '/' + row.id + (action === 'rotate' ? '/rotate' : ''), action === 'disable' ? { disabled: true } : {})) throw new Error('save failed') },
  })
  const rename = (row: KeyRow) => {
    let next = row.name
    modal.confirm({ title: t('hub.gateway.renameKey'), content: <Input aria-label={t('hub.gateway.keyName')} defaultValue={next} maxLength={80} onChange={event => { next = event.target.value }} />, okText: t('settings.save'), cancelText: t('common.cancel'), onOk: async () => { if (!next.trim() || !await change('PATCH', '/' + row.id, { name: next.trim() })) throw new Error('save failed') } })
  }
  return <section className="tt-gateway-keys" aria-label={t('hub.gateway.keys')}>
    <h3>{t('hub.gateway.keys')}</h3>
    {error && <Alert type="error" role="alert" message={t(error)} action={<Button disabled={busy} onClick={() => setVersion(previous => previous + 1)}>{t('capabilities.models.reread')}</Button>} />}
    {!view ? !error && <Spin /> : <>
      <form className="tt-gateway-key-create" onSubmit={event => { event.preventDefault(); if (name.trim()) void change('POST', '', { name: name.trim() }) }}>
        <Input aria-label={t('hub.gateway.keyName')} placeholder={t('hub.gateway.keyName')} value={name} maxLength={80} disabled={busy} onChange={event => setName(event.target.value)} />
        <Button type="primary" htmlType="submit" icon={<PlusIcon />} loading={busy} disabled={!name.trim() || busy}>{t('hub.gateway.generateKey')}</Button>
      </form>
      {view.keys.length ? <div className="tt-gateway-key-list">{view.keys.map(row => <article key={row.id} className="tt-gateway-key-row">
        <div><strong>{row.name || t('hub.gateway.existingKey')}</strong> <code>{row.suffix}</code> <Tag>{t(row.disabled ? 'hub.gateway.disabled' : 'hub.gateway.enabled')}</Tag></div>
        <div className="tt-gateway-key-actions">
          <Button disabled={busy} onClick={() => rename(row)}>{t('hub.gateway.renameKey')}</Button>
          <Button disabled={busy} onClick={() => row.disabled ? void change('PATCH', '/' + row.id, { disabled: false }) : confirm(row, 'disable')}>{t(row.disabled ? 'hub.gateway.enableKey' : 'hub.gateway.disableKey')}</Button>
          <Button disabled={busy} onClick={() => confirm(row, 'rotate')}>{t('hub.gateway.rotateKey')}</Button>
          <Button danger disabled={busy} onClick={() => confirm(row, 'delete')}>{t('hub.gateway.deleteKey')}</Button>
        </div>
      </article>)}</div> : <p className="agent-settings-hint">{t('hub.gateway.noKeys')}</p>}
    </>}
    <details><summary>{t('hub.gateway.manualKey')}</summary><GatewayAccessKey value={value} onChange={onChange} onChanged={() => { setVersion(previous => previous + 1); onChanged() }} /></details>
    <Modal destroyOnHidden open={!!issued} title={t('hub.gateway.generatedKey')} footer={<Button type="primary" onClick={() => setIssued('')}>{t('common.close')}</Button>} onCancel={() => setIssued('')} maskClosable={false}>
      <p>{t('hub.gateway.onceHint')}</p>
      <Input aria-label={t('hub.gateway.generatedKey')} value={issued} readOnly onFocus={event => event.target.select()} />
      <Button icon={<CopyIcon />} onClick={async () => { try { await navigator.clipboard.writeText(issued); message.success(t('common.copied')) } catch { message.error(t('hub.gateway.copyFailed')) } }}>{t('common.copy')}</Button>
    </Modal>
  </section>
}
