import { useId, useState } from 'react'
import { App as AntApp, Button, Input } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { revealInspector } from '../shell/inspector'
import { ChevronLeft, CloseIcon, ClockIcon } from '../../icons'
import { useLifecycleDraft } from './lifecycle-draft'
import AdaptivePanel from '../shell/AdaptivePanel'
import { sendSessionPrompt } from './session-actions'
import { blockingLifecycle, lifecycleAction, lifecycleEnded, useSessionLifecycle, type LifecycleOperation } from './session-lifecycle'
import './session-lifecycle.css'
import { useNativeSessionList } from './native-session-list'
import { nativeSessionName } from './session-record'

export function lifecycleStatus(op: LifecycleOperation, t: (key: string) => string) {
  if (op.state === 'attention') return t(op.kind === 'close' && op.receipts.stop ? 'session.lifecycle.cleanupFailed' : 'session.lifecycle.attention')
  if (op.state === 'cancelled') return t(op.receipts.compensate?.result?.retained ? 'session.lifecycle.cancelledRetained' : 'session.lifecycle.cancelled')
  if (op.state === 'succeeded' && op.intent.mode === 'keep' && op.receipts['remove-intent']) return t('session.lifecycle.retainedRemaining')
  if (op.state === 'succeeded' && op.intent.keepBranch) return t('session.lifecycle.cleanedBranchKept')
  if (op.state === 'succeeded') return t(op.kind === 'create' ? 'session.lifecycle.ready' : op.intent.mode === 'keep' ? 'session.lifecycle.retained' : 'session.lifecycle.cleaned')
  return t(op.cancelRequested ? 'session.lifecycle.cancelling' : op.kind === 'create' ? 'session.lifecycle.preparing' : op.receipts.stop ? 'session.lifecycle.cleaning' : 'session.lifecycle.closing')
}

export function LifecycleOperationView({ op, onOpen }: { op: LifecycleOperation; onOpen?: (name: string) => void }) {
  const { t, locale } = useI18n()
  const { message } = AntApp.useApp()
  const [busy, setBusy] = useState(false)
  const draftId = useId()
  const { draft, setDraft } = useLifecycleDraft(op.resourceId)
  const ready = op.kind === 'create' && op.state === 'succeeded'
  const act = async (action: 'retry' | 'cancel' | 'retain' | 'retain-branch') => {
    setBusy(true)
    try { await lifecycleAction(op, action) } catch { message.error(t('session.lifecycle.actionFailed')) } finally { setBusy(false) }
  }
  const send = async () => {
    setBusy(true)
    try { await sendSessionPrompt(op.resourceId, draft); setDraft(''); onOpen?.(op.resourceId) }
    catch { message.error(t('session.lifecycle.sendFailed')) } finally { setBusy(false) }
  }
  const stageKey = 'session.lifecycle.stage.' + op.stage
  const errorKey = 'session.lifecycle.error.' + op.errorCode
  return <div className="tt-lifecycle-detail">
    <div className="tt-lifecycle-summary">
      <strong>{op.intent.name || op.resourceId}</strong>
      <span role="status" className={op.state === 'attention' ? 'tt-lifecycle-error' : ''}>{lifecycleStatus(op, t)}</span>
      {!lifecycleEnded(op) && <span>{t(stageKey)}</span>}
      <span className="tt-lifecycle-path">{op.receipts.workspace?.result?.path || op.intent.path || op.intent.dir}</span>
      <span>{new Intl.DateTimeFormat(locale, { dateStyle: 'short', timeStyle: 'short' }).format(op.acceptedAt)}</span>
    </div>
    {op.errorCode && <p role="alert">{t(errorKey) === errorKey ? t('session.lifecycle.error.generic') : t(errorKey)}</p>}
    {op.kind === 'close' && op.receipts.stop && <p>{t('session.lifecycle.stopConfirmed')}</p>}
    {(op.intent.task || op.intent.launch?.task) && <details><summary>{t('session.lifecycle.originalTask')}</summary><p className="tt-lifecycle-task">{op.intent.task || op.intent.launch?.task}</p></details>}
    {op.kind === 'create' && op.state !== 'cancelled' && <div className="tt-lifecycle-draft">
      <label htmlFor={draftId}>{t('session.lifecycle.draft')}</label>
      <Input.TextArea id={draftId} value={draft} autoSize={{ minRows: 3, maxRows: 8 }} onChange={e => setDraft(e.target.value)} />
      <span>{t(ready ? 'session.lifecycle.draftReady' : 'session.lifecycle.draftHint')}</span>
      {ready && <Button type="primary" disabled={!draft.trim()} loading={busy} onClick={() => void send()}>{t('session.lifecycle.sendDraft')}</Button>}
    </div>}
    <div className="tt-lifecycle-actions">
      {op.state === 'attention' && op.errorCode !== 'LIFECYCLE_RESULT_UNKNOWN' && <Button loading={busy} onClick={() => void act('retry')}>{t('session.lifecycle.retry')}</Button>}
      {op.kind === 'create' && !lifecycleEnded(op) && !op.cancelRequested && <Button loading={busy} onClick={() => void act('cancel')}>{t('session.lifecycle.cancel')}</Button>}
      {op.kind === 'close' && op.state === 'attention' && !op.receipts.remove && <Button loading={busy} onClick={() => void act('retain')}>{t('session.lifecycle.retain')}</Button>}
      {op.kind === 'close' && op.state === 'attention' && op.receipts.remove && <Button loading={busy} onClick={() => void act('retain-branch')}>{t('session.lifecycle.keepBranch')}</Button>}
      {ready && onOpen && <Button onClick={() => onOpen(op.resourceId)}>{t('session.lifecycle.open')}</Button>}
    </div>
    <details><summary>{t('session.lifecycle.records')}</summary><dl>
      <dt>{t('session.lifecycle.operation')}</dt><dd>{op.operationId}</dd>
      {Object.entries(op.receipts).filter(([stage]) => !stage.endsWith('-intent')).map(([stage, receipt]) => <div key={stage}><dt>{t('session.lifecycle.stage.' + stage)}</dt><dd>{new Intl.NumberFormat(locale).format(receipt.durationMs)} ms</dd></div>)}
      {op.errorDetail && <><dt>{t('session.lifecycle.errorDetail')}</dt><dd>{op.errorDetail}</dd></>}
    </dl></details>
  </div>
}

export function SessionLifecycleInbox({ onOpen, compact = false }: { onOpen: (name: string) => void; compact?: boolean }) {
  const { phone } = useLayout()
  const { t, locale } = useI18n()
  const operations = useSessionLifecycle()
  const native = useNativeSessionList(true, true)
  const nativeClosures = native.value.filter(record => record.lifecycle !== 'closed' && (record.lifecycle === 'closing' || record.closureError))
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const op = operations.value.find(o => o.operationId === selected)
  const active = operations.value.filter(o => !lifecycleEnded(o))
  const pendingCount = active.length + nativeClosures.filter(record => record.lifecycle === 'closing').length
  const show = () => { if (!phone) revealInspector(); setOpen(true) }
  const close = () => { if (selected) setSelected(null); else setOpen(false) }
  return <>
    {compact ? <button type="button" className="tt-mobile-topbar-icon" aria-label={t('session.lifecycle.inbox')} onClick={show}><ClockIcon size={20} />{pendingCount > 0 && <span className="bd">{new Intl.NumberFormat(locale).format(pendingCount)}</span>}</button> : <Button onClick={show}>{t('session.lifecycle.inbox')}{pendingCount > 0 ? ` (${new Intl.NumberFormat(locale).format(pendingCount)})` : ''}</Button>}
    <AdaptivePanel key={phone ? selected || 'list' : 'desktop'} open={open} title={t('session.lifecycle.inbox')} onClose={close}
      desktopHeader={<div className="tt-lifecycle-head">{selected ? <button type="button" className="tt-act" onClick={() => setSelected(null)}><ChevronLeft size={16} />{t('common.back')}</button> : <strong>{t('session.lifecycle.inbox')}</strong>}<button type="button" className="tt-act" aria-label={t('common.close')} onClick={() => { setOpen(false); setSelected(null) }}><CloseIcon size={16} /></button></div>}>
      <div className="tt-lifecycle-panel">
        <div className="tt-lifecycle-scroll">
          {operations.failed && <p role="alert">{t('session.lifecycle.loadFailed')}</p>}
          {op ? <LifecycleOperationView key={op.operationId} op={op} onOpen={name => { setOpen(false); setSelected(null); onOpen(name) }} /> : active.length === 0 && nativeClosures.length === 0 ? <p>{t('session.lifecycle.empty')}</p> : active.map(o => <button type="button" className="tt-lifecycle-row" key={o.operationId} onClick={() => setSelected(o.operationId)}>
            <strong>{o.intent.name || o.resourceId}</strong><span>{lifecycleStatus(o, t)}</span>
          </button>)}
          {!op && nativeClosures.map(record => <button type="button" className="tt-lifecycle-row" key={record.nativeSessionId} onClick={() => { setOpen(false); onOpen(nativeSessionName(record.nativeSessionId)) }}>
            <strong>{record.title}</strong><span>{t(record.closureError ? 'session.lifecycle.attention' : record.lifecycle === 'closed' ? 'session.lifecycle.nativeClosed' : 'session.lifecycle.closing')}</span>
          </button>)}
        </div>
      </div>
    </AdaptivePanel>
  </>
}

export function PendingSessionLifecycle({ name }: { name: string }) {
  const { value } = useSessionLifecycle()
  const op = blockingLifecycle(value, name)
  return op ? <div className="tt-lifecycle-guard"><LifecycleOperationView key={op.operationId} op={op} /></div> : null
}

export function SessionLifecycleDraftNotice({ name }: { name: string }) {
  const { phone } = useLayout()
  const { value } = useSessionLifecycle()
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const op = value.find(item => item.resourceId === name && item.kind === 'create' && item.state === 'succeeded')
  const { draft } = useLifecycleDraft(name)
  if (!op || !draft) return null
  return <>
    <Button className="tt-lifecycle-draft-notice" onClick={() => { if (!phone) revealInspector(); setOpen(true) }}>{t('session.lifecycle.savedDraft')}</Button>
    <AdaptivePanel open={open} title={t('session.lifecycle.draft')} onClose={() => setOpen(false)} layer="session" desktopHeader={<div className="tt-lifecycle-head"><strong>{t('session.lifecycle.draft')}</strong><button type="button" className="tt-act" aria-label={t('common.close')} onClick={() => setOpen(false)}><CloseIcon size={16} /></button></div>}>
      <div className="tt-lifecycle-scroll"><LifecycleOperationView key={op.operationId} op={op} onOpen={() => setOpen(false)} /></div>
    </AdaptivePanel>
  </>
}
