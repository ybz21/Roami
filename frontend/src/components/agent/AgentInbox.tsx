import { useEffect, useRef, useState } from 'react'
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
import { useAgentData } from './useAgentData'
import { notificationDestination } from './notification-destination'
import './agent-notifications.css'

function noticePreview(text = '') {
  return text.replace(/!?\[([^\]\n]+)\]\([^\n)]*(?:\)|$)/gu, '$1').replace(/`([^`]+)`/gu, '$1').replace(/\*\*([^*\n]+)\*\*/gu, '$1')
}

export default function AgentInbox({ inbox, select, onNavigate, conversationId }: { conversationId?: string; inbox: AgentInboxState; onNavigate?: () => void; select: (cid: string, branch?: string, message?: string) => void }) {
  const { t, locale } = useI18n()
  const [unreadOnly, setUnreadOnly] = useState(false), [busy, setBusy] = useState(false), [failed, setFailed] = useState(false)
  const query = conversationId ? '&conversationId=' + encodeURIComponent(conversationId) : ''
  const summary = useAgentData<{ cursor: number; unread: number; conversationId?: string }>(conversationId ? '/agent/notifications/summary?conversationId=' + encodeURIComponent(conversationId) : null, 10000)
  const pages = usePagedAgentData<AgentNotice>('/agent/notification-list?limit=20&unreadOnly=' + unreadOnly + query, 10000)
  const scope = agentDataKey('/agent/notification-list' + query)
  const [acknowledged, setAcknowledged] = useState({ scope, cursor: 0 })
  const scopedSummary = summary.value?.conversationId === conversationId ? summary.value : undefined
  const readThrough = acknowledged.scope === scope ? acknowledged.cursor : 0
  const notices = pages.items.filter(n => (!conversationId || n.conversation_id === conversationId) && (!unreadOnly || !n.read && n.id > readThrough))
  const container = useRef<HTMLDivElement>(null)
  useBoundaryLoad(container, () => { void pages.loadMore() }, pages.hasMore && !pages.loadingMore && !pages.moreFailed)
  const navigation = useRef(0)
  useEffect(() => () => { navigation.current++ }, [scope])
  const openNotice = async (notice: Pick<AgentNotice, 'conversation_id' | 'branch_id' | 'message_id'>) => {
    const version = ++navigation.current, origin = location.hash, nodeScope = scope
    setFailed(false)
    try {
      const destination = await notificationDestination(notice, inbox.conversations[0]?.id || '')
      if (version !== navigation.current || origin !== location.hash || nodeScope !== agentDataKey('/agent/notification-list' + query)) return
      if (destination) { onNavigate?.(); location.hash = destination }
      else select(notice.conversation_id, notice.branch_id, notice.message_id)
    } catch { if (version === navigation.current) setFailed(true) }
  }
  const markAll = async () => {
    setBusy(true); setFailed(false)
    const cursor = Math.max((conversationId ? scopedSummary?.cursor : inbox.cursor) || 0, ...notices.map(n => n.id))
    try { await api('POST', conversationId ? '/agent/conversations/' + encodeURIComponent(conversationId) + '/read' : '/agent/notifications/read', { eventId: cursor }); setAcknowledged({ scope, cursor }); pages.refresh(); summary.refresh() }
    catch { setFailed(true) }
    finally { setBusy(false); inbox.refresh() }
  }
  return <div ref={container} className="agent-notifications-body agent-inbox">
    <div className="agent-inbox-toolbar"><div role="group" aria-label={t('agent.notification.messages')}>
      <button type="button" className="tt-act" aria-pressed={!unreadOnly} onClick={() => setUnreadOnly(false)}>{t('agent.notification.all')}</button>
      <button type="button" className="tt-act" aria-pressed={unreadOnly} onClick={() => setUnreadOnly(true)}>{t('agent.notification.unread')}</button>
    </div><button type="button" className="tt-act" disabled={busy || !(conversationId ? scopedSummary?.unread ?? notices.filter(item => !item.read).length : inbox.unread)} onClick={() => { void markAll() }}>{t('agent.notification.readAll')}</button></div>
    {failed && <p role="alert">{t('agent.requestFailed')}</p>}
    {!unreadOnly && <section><h3>{t('agent.notification.reminders')}</h3><AgentReminders conversationId={conversationId} select={(cid, branch, message) => { void openNotice({ conversation_id: cid, branch_id: branch || '', message_id: message }) }} /></section>}
    <section className="agent-panel-list"><h3>{t('agent.notification.messages')}</h3>
      {pages.loading && <Spin />}
      {pages.failed && <p role="alert">{t('agent.requestFailed')}<button type="button" className="tt-act" onClick={pages.refresh}>{t('agent.retry')}</button></p>}
      {!pages.loading && !pages.failed && !notices.length && <p className="agent-muted">{t('agent.noNotifications')}</p>}
      {notices.map(n => <button type="button" className="agent-notice" data-unread={!n.read && n.id > readThrough} key={n.id} onClick={() => { void openNotice(n) }}>
        <b>{n.title === 'New conversation' ? t('agent.new') : n.title}</b><span>{noticePreview(n.summary)}</span><small>{new Date(n.created_ms).toLocaleString(locale)}</small>
      </button>)}
      <AgentPageBoundary more={pages.hasMore} loading={pages.loadingMore} failed={pages.moreFailed} load={() => { void pages.loadMore() }} />
    </section>
  </div>
}
