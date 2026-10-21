import { memo } from 'react'
import { BotIcon, ChevronRight, WarnIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { activityReason, activityState } from './AgentActivity'
import type { AgentActivityItem } from './agent-protocol'

function AgentTaskActivity({ items, onTask }: { items: AgentActivityItem[]; onTask: (id: string) => void }) {
  const { t } = useI18n()
  return <>{items.map(item => {
    const state = activityState(item.state), task = item.kind === 'task'
    const failed = ['failed', 'unknown', 'interrupted'].includes(state)
    const label = task ? item.title || t('agent.task.untitled') : t(item.kind === 'turn' ? 'agent.activity.reply' : 'agent.activity.unconfirmed')
    return <section key={item.id} className={`agent-task-progress${failed ? ' is-failed' : ''}`} data-activity-id={item.id} data-state={state}>
      <div className="agent-task-progress-line">{failed ? <WarnIcon size={16} /> : <BotIcon size={16} />}<strong>{label}</strong><span>{t('agent.state.' + state)}</span>{item.taskId && <button type="button" className="tt-act" aria-label={t('agent.task.viewNamed', { name: label })} onClick={() => onTask(item.taskId!)}><ChevronRight size={18} /></button>}</div>
      {failed && <p role="status">{state === 'unknown' ? t('agent.activity.outcomeUnknown') : activityReason(item.errorCode, t)}</p>}
    </section>
  })}</>
}
export default memo(AgentTaskActivity)
