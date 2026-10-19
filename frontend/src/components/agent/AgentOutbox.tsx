import { useState } from 'react'
import { Input } from 'antd'
import { ArrowUp, CloseIcon, FileTextIcon, PencilIcon, RefreshIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { useAgentOutbox } from './useAgentOutbox'

export default function AgentOutbox({ outbox, ready }: { outbox: ReturnType<typeof useAgentOutbox>; ready: boolean }) {
  const { t } = useI18n(), [editing, setEditing] = useState(''), [text, setText] = useState('')
  if (!outbox.items.length) return null
  return <section className="agent-outbox" aria-label={t('agent.outbox.title')}>
    <div className="agent-outbox-head"><span>{t(outbox.paused ? 'agent.outbox.pausedCount' : 'agent.outbox.count', { count: outbox.items.length })}</span><button type="button" className="tt-act" onClick={() => outbox.pause(!outbox.paused)}>{t(outbox.paused ? 'agent.outbox.resume' : 'agent.outbox.pause')}</button></div>
    {outbox.storageFailed && <p className="agent-outbox-warning" role="alert">{t('agent.outbox.storageFailed')}</p>}
    <div className="agent-outbox-list">{outbox.items.map((item, index) => <div className="agent-outbox-item" key={item.id}>
      <div className="agent-outbox-content"><small>{t(item.state === 'failed' ? 'agent.outbox.failed' : item.state === 'unconfirmed' ? 'agent.outbox.unconfirmed' : item.id === outbox.sending ? 'agent.outbox.sending' : 'agent.outbox.position', { position: index + 1 })}</small>
        {editing === item.id ? <><Input.TextArea aria-label={t('agent.outbox.edit')} value={text} maxLength={100000} autoSize={{ minRows: 1, maxRows: 4 }} onChange={event => setText(event.target.value)} /><div className="agent-outbox-edit"><button type="button" className="tt-act" onClick={() => setEditing('')}>{t('common.cancel')}</button><button type="button" className="tt-act ok" disabled={!text.trim() && !item.attachments.length} onClick={() => { if (outbox.edit(item.id, text.trim())) setEditing('') }}>{t('agent.save')}</button></div></> : <p>{item.text}</p>}
        {!!item.attachments.length && <ul className="agent-outbox-files">{item.attachments.map(file => <li key={file.id}><FileTextIcon size={14} /><span>{file.name}</span></li>)}</ul>}
        {(item.state === 'failed' || item.state === 'unconfirmed') && <span className="agent-outbox-warning">{t(item.state === 'failed' ? 'agent.outbox.failedHint' : 'agent.outbox.unknownHint')}</span>}
      </div>
      <div className="agent-outbox-actions">
        {item.state === 'failed' || item.state === 'unconfirmed' ? <button type="button" className="tt-act" aria-label={t('agent.retry')} disabled={!!outbox.sending} onClick={() => outbox.retry(item.id)}><RefreshIcon size={16} /></button> : <><button type="button" className="tt-act" aria-label={t('agent.outbox.sendNow')} disabled={!ready || !!outbox.sending || !!editing} onClick={() => outbox.sendNow(item.id)}><ArrowUp size={16} /></button><button type="button" className="tt-act" aria-label={t('agent.outbox.edit')} disabled={!!outbox.sending || !!editing} onClick={() => { outbox.pause(true); setEditing(item.id); setText(item.text) }}><PencilIcon size={16} /></button></>}
        <button type="button" className="tt-act" aria-label={t('agent.outbox.remove')} disabled={item.id === outbox.sending} onClick={() => { if (outbox.remove(item.id) && editing === item.id) setEditing('') }}><CloseIcon size={16} /></button>
      </div>
    </div>)}</div>
    <p className="agent-outbox-local">{t('agent.outbox.localHint')}</p>
  </section>
}
