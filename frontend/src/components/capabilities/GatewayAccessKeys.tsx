import { useEffect, useRef, useState, type ReactNode } from 'react'
import { App } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { CopyIcon, PlusIcon, MoreIcon, ShieldIcon } from '../../icons'
import { catalogFailure } from './model-hub-api'
import { Alert, Button, Dropdown, Input, Spin } from './model-controls'
import GatewayAccessKey from './GatewayAccessKey'
import GatewayInspector from './GatewayInspector'
import { useGatewayFixedKey } from './gateway-fixed-key'

type KeyRow = { id: string; name: string; suffix: string; disabled: boolean }
type KeyView = { revision: string; keys: KeyRow[] }
type Editor = { kind: 'create' | 'rename' | 'fixed' | 'issued'; id?: string }
const path = '/agent/model-gateway/access-keys'
export default function GatewayAccessKeys({ active = true, onChanged, value, onChange, children }: { active?: boolean; onChanged: () => void; value: string; onChange: (value: string) => void; children?: ReactNode }) {
  const { t, locale } = useI18n(), { message, modal } = App.useApp(), fixed = useGatewayFixedKey()
  const [view, setView] = useState<KeyView | null>(null), [name, setName] = useState(''), [renameName, setRenameName] = useState(''), [editor, setEditor] = useState<Editor | null>(null)
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [version, setVersion] = useState(0), [issued, setIssued] = useState('')
  const activeRef = useRef(active), viewRef = useRef(view), writing = useRef(false), opener = useRef<HTMLElement | null>(null)
  const createButton = useRef<HTMLButtonElement>(null), fixedButton = useRef<HTMLButtonElement>(null), rowButtons = useRef(new Map<string, HTMLButtonElement>())
  activeRef.current = active
  useEffect(() => { if (!active) { setIssued(''); setEditor(null) } }, [active])
  useEffect(() => {
    const abort = new AbortController()
    setLoading(true)
    void api('GET', path, undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) { viewRef.current = data; setView(data); setError('') } }).catch(cause => { if (!abort.signal.aborted) setError(catalogFailure(cause)) }).finally(() => { if (!abort.signal.aborted) setLoading(false) })
    return () => abort.abort()
  }, [version])
  const locked = busy || loading || fixed.busy || fixed.loading
  const restoreFocus = () => setTimeout(() => (opener.current?.isConnected ? opener.current : createButton.current)?.focus({ preventScroll: true }), 0)
  const close = () => { if (busy || fixed.busy) return; setEditor(null); setIssued(''); restoreFocus() }
  const open = (next: Editor, trigger?: HTMLElement | null) => { opener.current = trigger || document.activeElement as HTMLElement; setEditor(next); if (next.kind === 'rename') setRenameName(view?.keys.find(row => row.id === next.id)?.name || '') }
  const reload = () => { setLoading(true); setVersion(previous => previous + 1); fixed.retry() }
  const change = async (method: string, suffix = '', fields: Record<string, unknown> = {}) => {
    if (!viewRef.current || writing.current || fixed.busy) return false
    writing.current = true; setBusy(true); setError('')
    try {
      const { data } = await api(method, path + suffix, { revision: viewRef.current.revision, ...fields })
      const { apiKey, ...metadata } = data as KeyView & { apiKey?: string }
      viewRef.current = metadata; setView(metadata)
      if (method === 'POST' && !suffix) setName('')
      if (activeRef.current) { if (apiKey) { setIssued(apiKey); setEditor({ kind: 'issued' }) } else { setEditor(null); restoreFocus() } }
      fixed.retry(); onChanged(); return true
    } catch (cause) { setError(catalogFailure(cause)); return false }
    finally { writing.current = false; setBusy(false) }
  }
  const keyName = (row: KeyRow) => row.name || t(row.id === fixed.view?.id ? 'gatewayWorkspace.fixedKey' : 'hub.gateway.existingKey')
  const confirm = (row: KeyRow, action: 'rotate' | 'delete' | 'disable') => { opener.current = rowButtons.current.get(row.id) || null; return modal.confirm({
    className: 'tt-gateway-key-dialog', title: t(`hub.gateway.${action}Key`), content: <><strong>{keyName(row)}</strong><p>{t(`hub.gateway.${action}Hint`)}</p></>, okText: t(`hub.gateway.${action}Key`), cancelText: t('common.cancel'),
    onOk: async () => { if (!await change(action === 'rotate' ? 'POST' : action === 'delete' ? 'DELETE' : 'PATCH', '/' + encodeURIComponent(row.id) + (action === 'rotate' ? '/rotate' : ''), action === 'disable' ? { disabled: true } : {})) throw new Error('save failed') },
  }) }
  const editingName = editor?.kind === 'rename', title = t(editor?.kind === 'issued' ? 'hub.gateway.generatedKey' : editor?.kind === 'fixed' ? 'gatewayWorkspace.manualKey' : editingName ? 'hub.gateway.renameKey' : 'gatewayWorkspace.newKey')
  const panel = editor && <GatewayInspector title={title} onClose={close} busy={busy || fixed.busy}>
    {editor.kind === 'fixed' ? <GatewayAccessKey controller={fixed} value={value} onChange={onChange} onCancel={close} onSaved={() => { setEditor(null); restoreFocus() }} onChanged={() => { setLoading(true); setVersion(previous => previous + 1); onChanged() }} />
      : editor.kind === 'issued' ? <><div className="tt-gateway-editor-scroll"><p className="tt-gateway-notice">{t('hub.gateway.onceHint')}</p><Input.TextArea aria-label={t('hub.gateway.generatedKey')} value={issued} readOnly onFocus={event => event.target.select()} /><Button icon={<CopyIcon />} onClick={async () => { try { await navigator.clipboard.writeText(issued); message.success(t('common.copied')) } catch { message.error(t('hub.gateway.copyFailed')) } }}>{t('gatewayWorkspace.copyKey')}</Button></div><footer className="tt-gateway-editor-footer"><Button type="primary" onClick={close}>{t('gatewayWorkspace.keySaved')}</Button></footer></>
      : <form className="tt-gateway-key-form" onSubmit={event => { event.preventDefault(); const next = (editingName ? renameName : name).trim(); if (next) void change(editingName ? 'PATCH' : 'POST', editingName ? '/' + encodeURIComponent(editor.id!) : '', { name: next }) }}><div className="tt-gateway-editor-scroll"><p className="agent-settings-hint">{t(editingName ? 'gatewayWorkspace.renameHint' : 'gatewayWorkspace.createHint')}</p>{error && <Alert message={t(error)} action={<Button disabled={locked} onClick={reload}>{t('capabilities.models.reread')}</Button>} />}<label className="agent-settings-field"><span>{t('hub.gateway.keyName')}</span><Input aria-label={t('hub.gateway.keyName')} value={editingName ? renameName : name} maxLength={80} disabled={busy} autoComplete="off" placeholder={t('gatewayWorkspace.namePlaceholder')} onChange={event => editingName ? setRenameName(event.target.value) : setName(event.target.value)} /></label></div><footer className="tt-gateway-editor-footer"><Button disabled={busy} onClick={close}>{t('common.cancel')}</Button><Button type="primary" htmlType="submit" loading={busy} disabled={locked || !(editingName ? renameName : name).trim()}>{t(editingName ? 'settings.save' : 'hub.gateway.generateKey')}</Button></footer></form>}
  </GatewayInspector>
  return <div className="tt-gateway-layout"><div className="tt-gateway-scroll">{children}<section className="tt-gateway-keys" aria-label={t('hub.gateway.keys')}>
    <div className="tt-gateway-section-head"><h3>{t('hub.gateway.keys')}{!!view?.keys.length && <span className="tt-gateway-count">{new Intl.NumberFormat(locale).format(view.keys.length)}</span>}</h3><div className="tt-gateway-section-actions"><Button ref={createButton} type="primary" icon={<PlusIcon />} disabled={!view || locked} onClick={() => open({ kind: 'create' })}>{t('gatewayWorkspace.newKey')}</Button><Dropdown disabled={locked} menu={{ items: [{ key: 'fixed', label: t(fixed.view?.hasKey ? 'gatewayWorkspace.replaceFixed' : 'gatewayWorkspace.manualKey') }], onClick: () => open({ kind: 'fixed' }, fixedButton.current) }}><Button ref={fixedButton} type="text" icon={<MoreIcon />} aria-label={t('gatewayWorkspace.more')} disabled={locked} /></Dropdown></div></div>
    <p className="agent-settings-hint">{t('gatewayWorkspace.keyHint')}</p>
    {error && !editor && <Alert message={t(error)} action={<Button disabled={locked} onClick={reload}>{t('capabilities.models.reread')}</Button>} />}
    {fixed.error && editor?.kind !== 'fixed' && <Alert message={t(fixed.error)} action={<Button disabled={locked} onClick={reload}>{t('capabilities.models.reread')}</Button>} />}
    {!view ? !error && <Spin /> : view.keys.length ? <div className="tt-gateway-key-list"><div className="tt-gateway-key-columns" aria-hidden="true"><span>{t('hub.gateway.keyName')}</span><span>{t('gatewayWorkspace.suffix')}</span><span>{t('gatewayWorkspace.state')}</span><span /></div>{view.keys.map(row => <article key={row.id} className="tt-gateway-key-row"><div className="tt-gateway-key-identity"><ShieldIcon /><strong>{keyName(row)}</strong>{row.id === fixed.view?.id && row.name && <span className="tt-gateway-pill">{t('gatewayWorkspace.fixedKey')}</span>}</div><code className="tt-gateway-key-suffix">****{row.suffix}</code><span className={'tt-gateway-status' + (row.disabled ? '' : ' is-enabled')}>{t(row.disabled ? 'hub.gateway.disabled' : 'hub.gateway.enabled')}</span><Dropdown disabled={locked} menu={{ items: ['rename', row.disabled ? 'enable' : 'disable', 'rotate', 'delete'].map(key => ({ key, label: t('hub.gateway.' + key + 'Key') })), onClick: ({ key }) => { if (key === 'rename') open({ kind: 'rename', id: row.id }, rowButtons.current.get(row.id)); else if (key === 'enable') void change('PATCH', '/' + encodeURIComponent(row.id), { disabled: false }); else confirm(row, key as 'disable' | 'rotate' | 'delete') } }}><Button ref={element => { if (element) rowButtons.current.set(row.id, element); else rowButtons.current.delete(row.id) }} type="text" icon={<MoreIcon />} aria-label={t('modelInteraction.manageKey', { name: keyName(row) })} disabled={locked} /></Dropdown></article>)}</div> : <p className="tt-gateway-empty">{t('hub.gateway.noKeys')}</p>}
  </section></div>{active && panel}</div>
}
