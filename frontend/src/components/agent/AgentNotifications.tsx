import { useState } from 'react'
import { Modal, Tabs } from 'antd'
import AgentNotificationSettings from './AgentNotificationSettings'
import AgentReminders from './AgentReminders'
import AgentDeliveryStatus from './AgentDeliveryStatus'
import './agent-notifications.css'
import { useI18n } from '../../i18n'
import type { AgentInboxState } from './useAgentInbox'

export default function AgentNotifications({ open, close, inbox, select, node }: { open: boolean; node?: string | null; close: () => void; inbox: AgentInboxState; select: (cid: string, branch?: string, message?: string) => void }) {
  const { t, locale } = useI18n()
  const [panel, setPanel] = useState('messages')
  const dismiss = () => { setPanel('messages'); close() }
  const choose = (cid: string, branch?: string, message?: string) => { dismiss(); select(cid, branch, message) }
  return <Modal open={open} title={t('agent.notifications')} footer={null} onCancel={dismiss} destroyOnClose centered width="calc(var(--sp-5) * 28)" className="agent-notifications-dialog" wrapClassName="agent-notifications-wrap">
    <Tabs key={node || 'local'} activeKey={panel} onChange={setPanel} destroyInactiveTabPane items={[
      { key: 'messages', label: t('agent.notification.messages'), children: <div className="agent-notifications-body">
    <div className="agent-panel-list">{!inbox.notices.length && <p className="agent-muted">{t('agent.noNotifications')}</p>}
      {inbox.notices.map((n) => {
        let text = ''
        try { text = JSON.parse(n.content_json).text || '' } catch { /* Keep the conversation link available. */ }
        return <button type="button" className="agent-notice" key={n.id} onClick={() => { dismiss(); select(n.conversation_id, n.branch_id, n.message_id) }}>
          <b>{n.title === 'New conversation' ? t('agent.new') : n.title}</b><span>{text}</span><small>{new Date(n.created_ms).toLocaleString(locale)}</small>
        </button>
      })}
    </div></div> },
      { key: 'reminders', label: t('agent.notification.reminders'), children: <AgentReminders select={choose} /> },
      { key: 'settings', label: t('agent.notification.settings'), children: <AgentNotificationSettings /> },
      { key: 'delivery', label: t('agent.notification.delivery'), children: <AgentDeliveryStatus select={choose} /> },
    ]} />
  </Modal>
}
