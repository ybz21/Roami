import { agentName, type AgentKind } from '../../agent-kind'
import { AgentLogo } from '../../icons'
import { useI18n } from '../../i18n'
import { TBtn } from './terminal-toolbar'
import './agent-view-toggle.css'

export default function AgentViewToggle({ agent, chat, onToggle }: { agent: AgentKind; chat: boolean; onToggle: () => void }) {
  const { t } = useI18n()
  return <TBtn className="agent-view-toggle" icon={<AgentLogo kind={agent} size={14} />} label={agentName(agent)} on={chat} pressed={chat}
    title={t(chat ? 'chat.switchToTerminal' : 'chat.switchToRendered', { name: agentName(agent) })} onClick={onToggle} />
}
