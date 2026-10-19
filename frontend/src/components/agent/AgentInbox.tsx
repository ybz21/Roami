import { useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import AgentReminders from './AgentReminders'
import type { AgentInboxState } from './useAgentInbox'
import './agent-notifications.css'

export default function AgentInbox({ inbox, select }: { inbox: AgentInboxState; select: (cid: string, branch?: string, message?: string) => void }) {
  const { t, locale } = useI18n()
  const [unreadOnly, setUnreadOnly] = useState(false), [busy, setBusy] = useState(false), [failed, setFailed] = useState(false)
  const markAll = async () => {
    setBusy(true); setFailed(false)
    const cursors = new Map<string, number>()
    inbox.notices.filter(n => !n.read).forEach(n => cursors.set(n.conversation_id, Math.max(cursors.get(n.conversation_id) || 0, n.id)))
    const results = await Promise.allSettled([...cursors].map(([cid, eventId]) => api('POST', `/agent/conversations/${encodeURIComponent(cid)}/read`, { eventId })))
    setFailed(results.some(result => result.status === 'rejected')); setBusy(false); inbox.refresh()
  }
  const notices = inbox.notices.filter(n => !unreadOnly || !n.read)
  return <div className="agent-notifications-body agent-inbox">
    <div className="agent-inbox-toolbar"><div role="group" aria-label={t('agent.notification.messages')}>
      <button type="button" className="tt-act" aria-pressed={!unreadOnly} onClick={() => setUnreadOnly(false)}>{t('agent.notification.all')}</button>
      <button type="button" className="tt-act" aria-pressed={unreadOnly} onClick={() => setUnreadOnly(true)}>{t('agent.notification.unread')}</button>
    </div><button type="button" className="tt-act" disabled={busy || !inbox.unread} onClick={() => { void markAll() }}>{t('agent.notification.readAll')}</button></div>
    {failed && <p role="alert">{t('agent.requestFailed')}</p>}
    {!unreadOnly && <section><h3>{t('agent.notification.reminders')}</h3><AgentReminders select={select} /></section>}
    <section className="agent-panel-list"><h3>{t('agent.notification.messages')}</h3>{!notices.length && <p className="agent-muted">{t('agent.noNotifications')}</p>}
      {notices.map(n => {
        let text = ''
        try { const value = JSON.parse(n.content_json).text; text = typeof value === 'string' ? value : '' } catch { /* Preserve navigation for legacy records. */ }
        return <button type="button" className="agent-notice" data-unread={!n.read} key={n.id} onClick={() => select(n.conversation_id, n.branch_id, n.message_id)}>
          <b>{n.title === 'New conversation' ? t('agent.new') : n.title}</b><span>{text}</span><small>{new Date(n.created_ms).toLocaleString(locale)}</small>
        </button>
      })}
    </section>
  </div>
}
