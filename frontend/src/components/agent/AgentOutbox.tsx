import { useState } from 'react'
import { Dropdown, Input } from 'antd'
import { ArrowUp, ClockIcon, FileTextIcon, MoreIcon, RefreshIcon, TrashIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { useAgentOutbox } from './useAgentOutbox'

export default function AgentOutbox({ outbox, ready, running }: { outbox: ReturnType<typeof useAgentOutbox>; ready: boolean; running: boolean }) {
  const { t } = useI18n(), [editing, setEditing] = useState(''), [text, setText] = useState(''), [expanded, setExpanded] = useState(false)
  if (!outbox.items.length) return null
  const countLabel = t(outbox.paused ? 'agent.outbox.pausedCount' : 'agent.outbox.count', { count: outbox.items.length })
  return <section className={`agent-outbox${expanded ? ' is-expanded' : ''}`} aria-label={t('agent.outbox.title')}>
    {outbox.storageFailed && <p className="agent-outbox-warning" role="alert">{t('agent.outbox.storageFailed')}</p>}
    <div className="agent-outbox-list">{(expanded || editing ? outbox.items : outbox.items.slice(0, 1)).map(item => <div className={`agent-outbox-item${editing === item.id ? ' is-editing' : ''}`} key={item.id}>
      <button type="button" className="tt-act agent-outbox-marker" aria-label={countLabel} aria-expanded={expanded} title={t('agent.outbox.localHint')} disabled={outbox.items.length < 2} onClick={() => setExpanded(value => !value)}><ClockIcon size={16} />{outbox.items.length > 1 && <small>{outbox.items.length}</small>}</button>
      <div className="agent-outbox-content">
        {(outbox.paused || item.state !== 'waiting') && <small>{t(item.state === 'failed' ? 'agent.outbox.failed' : item.state === 'unconfirmed' ? 'agent.outbox.unconfirmed' : item.state === 'sending' ? 'agent.outbox.sending' : 'agent.outbox.paused')}</small>}
        {editing === item.id ? <><Input.TextArea aria-label={t('agent.outbox.edit')} value={text} maxLength={100000} autoSize={{ minRows: 1, maxRows: 4 }} onChange={event => setText(event.target.value)} /><div className="agent-outbox-edit"><button type="button" className="tt-act" onClick={() => setEditing('')}>{t('common.cancel')}</button><button type="button" className="tt-act ok" disabled={!text.trim() && !item.attachments.length} onClick={() => { if (outbox.edit(item.id, text.trim())) setEditing('') }}>{t('agent.save')}</button></div></> : <p title={item.text || item.attachments.map(file => file.name).join(', ')}>{item.text || item.attachments.map(file => file.name).join(', ')}</p>}
        {expanded && !!item.attachments.length && <ul className="agent-outbox-files">{item.attachments.map(file => <li key={file.id}><FileTextIcon size={14} /><span>{file.name}</span></li>)}</ul>}
        {(item.state === 'failed' || item.state === 'unconfirmed') && <span className="agent-outbox-warning">{t(item.state === 'failed' ? 'agent.outbox.failedHint' : 'agent.outbox.unknownHint')}</span>}
      </div>
      <div className="agent-outbox-actions">
        {item.state === 'failed' || item.state === 'unconfirmed' ? <button type="button" className="tt-act" aria-label={t('agent.retry')} disabled={!!outbox.sending} onClick={() => outbox.retry(item.id)}><RefreshIcon size={16} /></button> : <button type="button" className="tt-act agent-outbox-priority" aria-label={t(running ? 'agent.outbox.interruptNow' : 'agent.outbox.sendNow')} disabled={!ready || !!outbox.sending || !!editing} onClick={() => outbox.sendNow(item.id)}><ArrowUp size={16} /><span>{t('agent.outbox.runNow')}</span></button>}
        <button type="button" className="tt-act" aria-label={t('agent.outbox.remove')} disabled={item.id === outbox.sending} onClick={() => { if (outbox.remove(item.id) && editing === item.id) setEditing('') }}><TrashIcon size={16} /></button>
        <Dropdown trigger={['click']} overlayClassName="agent-outbox-menu" menu={{ items: [
          { key: 'edit', label: t('agent.outbox.edit'), disabled: item.state !== 'waiting' || !!outbox.sending || !!editing },
          { key: 'pause', label: t(outbox.paused ? 'agent.outbox.resume' : 'agent.outbox.pause') },
          { key: 'expand', label: t(expanded ? 'agent.outbox.collapse' : 'agent.outbox.expand', { count: outbox.items.length }) },
          { type: 'divider' }, { key: 'local', label: t('agent.outbox.localHint'), disabled: true },
        ], onClick: ({ key }) => { if (key === 'edit') { outbox.pause(true); setExpanded(true); setEditing(item.id); setText(item.text) } else if (key === 'pause') outbox.pause(!outbox.paused); else if (key === 'expand') setExpanded(value => !value) } }}><button type="button" className="tt-act" aria-label={t('agent.outbox.more')}><MoreIcon size={16} /></button></Dropdown>
      </div>
    </div>)}</div>
  </section>
}
