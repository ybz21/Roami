import { ClockIcon, PlusIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { AgentConversation, AgentNotice } from './agent-protocol'

export function conversationTitle(item: AgentConversation, fallback: string) { return item.title === 'New conversation' ? fallback : item.title }

export default function AgentHistory({ conversations, notices, active, select, create }: {
  conversations: AgentConversation[]; notices: AgentNotice[]; active: string
  select: (cid: string) => void; create: () => void
}) {
  const { t } = useI18n()
  return <section className="agent-history" aria-label={t('agent.history')}>
    <div className="agent-history-head"><span>{t('agent.history')}</span><button type="button" className="tt-act" aria-label={t('agent.new')} onClick={create}><PlusIcon /></button></div>
    {conversations.slice(0, 8).map((c) => <button type="button" key={c.id} className="agent-history-row" aria-current={c.id === active ? 'page' : undefined} onClick={() => select(c.id)}>
      <ClockIcon /><span>{conversationTitle(c, t('agent.new'))}</span>{notices.some((n) => n.conversation_id === c.id) && <i className="agent-unread-dot" aria-label={t('agent.unread')} />}
    </button>)}
  </section>
}
