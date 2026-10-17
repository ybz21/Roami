import { Modal } from 'antd'
import { useI18n } from '../../i18n'
import type { AgentInboxState } from './useAgentInbox'

export default function AgentNotifications({ open, close, inbox, select }: { open: boolean; close: () => void; inbox: AgentInboxState; select: (cid: string, branch?: string) => void }) {
  const { t, locale } = useI18n()
  return <Modal open={open} title={t('agent.notifications')} footer={null} onCancel={close}>
    <div className="agent-panel-list">{!inbox.notices.length && <p className="agent-muted">{t('agent.noNotifications')}</p>}
      {inbox.notices.map((n) => {
        let text = ''
        try { text = JSON.parse(n.content_json).text || '' } catch { /* Keep the conversation link available. */ }
        return <button type="button" className="agent-notice" key={n.id} onClick={() => { close(); select(n.conversation_id, n.branch_id) }}>
          <b>{n.title === 'New conversation' ? t('agent.new') : n.title}</b><span>{text}</span><small>{new Date(n.created_ms).toLocaleString(locale)}</small>
        </button>
      })}
    </div>
  </Modal>
}
