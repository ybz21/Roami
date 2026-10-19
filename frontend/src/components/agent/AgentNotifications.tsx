import { Modal } from 'antd'
import AgentInbox from './AgentInbox'
import './agent-notifications.css'
import { useI18n } from '../../i18n'
import type { AgentInboxState } from './useAgentInbox'

export default function AgentNotifications({ open, close, inbox, select, node }: { open: boolean; node?: string | null; close: () => void; inbox: AgentInboxState; select: (cid: string, branch?: string, message?: string) => void }) {
  const { t } = useI18n()
  return <Modal open={open} title={t('agent.notifications')} footer={null} onCancel={close} destroyOnClose centered width="calc(var(--sp-5) * 28)" className="agent-notifications-dialog" wrapClassName="agent-notifications-wrap">
    <AgentInbox key={node || 'local'} inbox={inbox} select={(...args) => { close(); select(...args) }} />
  </Modal>
}
