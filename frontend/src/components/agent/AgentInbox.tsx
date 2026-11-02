import { useRef, useState } from 'react'
import { Spin } from 'antd'
import { agentDataKey } from './agent-data-cache'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import AgentReminders from './AgentReminders'
import type { AgentInboxState } from './useAgentInbox'
import type { AgentNotice } from './agent-protocol'
import { usePagedAgentData } from './usePagedAgentData'
import { useBoundaryLoad } from './useBoundaryLoad'
import AgentPageBoundary from './AgentPageBoundary'
import './agent-notifications.css'

export default function AgentInbox({ inbox, select }: { inbox: AgentInboxState; select: (cid: string, branch?: string, message?: string) => void }) {
  const { t, locale } = useI18n()
  const [unreadOnly, setUnreadOnly] = useState(false), [busy, setBusy] = useState(false), [failed, setFailed] = useState(false)
  const pages = usePagedAgentData<AgentNotice>('/agent/notification-list?limit=20&unreadOnly=' + unreadOnly, 10000)
  const scope = agentDataKey('/agent/notification-list')
  const [acknowledged, setAcknowledged] = useState({ scope, cursor: 0 })
  const readThrough = acknowledged.scope === scope ? acknowledged.cursor : 0
  const notices = pages.items.filter(n => !unreadOnly || !n.read && n.id > readThrough)
  const container = useRef<HTMLDivElement>(null)
  useBoundaryLoad(container, () => { void pages.loadMore() }, pages.hasMore && !pages.loadingMore && !pages.moreFailed)
  const markAll = async () => {
    setBusy(true); setFailed(false)
    const cursor = Math.max(inbox.cursor || 0, ...pages.items.map(n => n.id))
    try { await api('POST', '/agent/notifications/read', { eventId: cursor }); setAcknowledged({ scope, cursor }); pages.refresh() }
    catch { setFailed(true) }
    finally { setBusy(false); inbox.refresh() }
  }
  return <div ref={container} className="agent-notifications-body agent-inbox">
    <div className="agent-inbox-toolbar"><div role="group" aria-label={t('agent.notification.messages')}>
      <button type="button" className="tt-act" aria-pressed={!unreadOnly} onClick={() => setUnreadOnly(false)}>{t('agent.notification.all')}</button>
      <button type="button" className="tt-act" aria-pressed={unreadOnly} onClick={() => setUnreadOnly(true)}>{t('agent.notification.unread')}</button>
    </div><button type="button" className="tt-act" disabled={busy || !inbox.unread} onClick={() => { void markAll() }}>{t('agent.notification.readAll')}</button></div>
    {failed && <p role="alert">{t('agent.requestFailed')}</p>}
    {!unreadOnly && <section><h3>{t('agent.notification.reminders')}</h3><AgentReminders select={select} /></section>}
    <section className="agent-panel-list"><h3>{t('agent.notification.messages')}</h3>
      {pages.loading && <Spin />}
      {pages.failed && <p role="alert">{t('agent.requestFailed')}<button type="button" className="tt-act" onClick={pages.refresh}>{t('agent.retry')}</button></p>}
      {!pages.loading && !pages.failed && !notices.length && <p className="agent-muted">{t('agent.noNotifications')}</p>}
      {notices.map(n => <button type="button" className="agent-notice" data-unread={!n.read && n.id > readThrough} key={n.id} onClick={() => select(n.conversation_id, n.branch_id, n.message_id)}>
        <b>{n.title === 'New conversation' ? t('agent.new') : n.title}</b><span>{n.summary}</span><small>{new Date(n.created_ms).toLocaleString(locale)}</small>
      </button>)}
      <AgentPageBoundary more={pages.hasMore} loading={pages.loadingMore} failed={pages.moreFailed} load={() => { void pages.loadMore() }} />
    </section>
  </div>
}
