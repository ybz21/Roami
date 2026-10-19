import { useI18n } from '../../i18n'
import { useCurrentNodeId } from '../cluster/node-url'
import AgentNotificationSettings from '../agent/AgentNotificationSettings'
import AgentDeliveryStatus from '../agent/AgentDeliveryStatus'
import '../agent/agent-notifications.css'

export function AgentMessageSettings() {
  const node = useCurrentNodeId(), { t } = useI18n()
  return <div key={node || 'local'}><AgentNotificationSettings /><details className="agent-task-log"><summary>{t('agent.notification.delivery')}</summary><AgentDeliveryStatus select={cid => { location.hash = '#/home/' + encodeURIComponent(cid) }} /></details></div>
}
