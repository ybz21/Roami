import { Fragment, useEffect, useState } from 'react'
import { BotIcon, CheckIcon, ChevronLeft, ChevronRight, ClockIcon, TerminalIcon } from '../../icons'
import { api } from '../../api'
import { taskGoal } from './agent-task-protocol'
import { useI18n } from '../../i18n'
import AgentActivity, { activityState } from './AgentActivity'
import type { AgentActivityItem, AgentTask } from './agent-protocol'

export default function AgentWorkspaceActivity({ items, cid, branch, onSession, onTask }: { items: AgentActivityItem[]; cid: string; branch: string; onSession: (id: string) => void; onTask: (id: string) => void }) {
  const { t, locale } = useI18n(), [selected, setSelected] = useState('')
  const [titles, setTitles] = useState<Record<string, string>>({}), [titleFailure, setTitleFailure] = useState(false), [retry, setRetry] = useState(0)
  const taskVersion = items.filter(item => item.kind === 'task').map(item => item.id + ':' + item.updatedMs).join(',')
  useEffect(() => {
    if (!cid || !taskVersion) return
    const abort = new AbortController()
    void api('GET', '/agent/tasks?conversationId=' + encodeURIComponent(cid), undefined, { signal: abort.signal }).then(({ data }: { data: AgentTask[] }) => { if (!abort.signal.aborted) { setTitles(Object.fromEntries(data.map(task => [task.id, taskGoal(task)]))); setTitleFailure(false) } }).catch(() => { if (!abort.signal.aborted) setTitleFailure(true) })
    return () => abort.abort()
  }, [cid, taskVersion, retry])
  const detail = items.find(item => item.id === selected)
  if (detail) return <div className="agent-workspace-detail"><button type="button" className="tt-act" onClick={() => setSelected('')}><ChevronLeft size={16} />{t('agent.workspace.activity')}</button><AgentActivity items={[detail]} conversationId={cid} branchId={branch} onSession={onSession} /></div>
  const now = new Date(), yesterday = new Date(now); yesterday.setDate(now.getDate() - 1)
  const dateKey = (date: Date) => date.toLocaleDateString('en-CA')
  let previous = ''
  const sorted = [...items].sort((a, b) => (b.updatedMs || b.startedMs || 0) - (a.updatedMs || a.startedMs || 0) || a.id.localeCompare(b.id))
  return <div className="agent-workspace-feed">
    <p className="agent-muted">{t('agent.workspace.activityHint')}</p>
    {titleFailure && <p role="alert">{t('agent.workspace.taskTitlesUnavailable')}<button type="button" className="tt-act" onClick={() => setRetry(value => value + 1)}>{t('agent.retry')}</button></p>}
    {!sorted.length && <p className="agent-workspace-empty">{t('agent.workspace.noActivity')}</p>}
    {sorted.map(item => {
      const ms = item.updatedMs || item.startedMs, date = Number.isFinite(ms) && ms > 0 ? new Date(ms) : null
      const day = date ? dateKey(date) : 'unknown', heading = day !== previous; previous = day
      const title = item.kind === 'turn' ? t('agent.activity.reply') : item.kind === 'task' ? titles[item.taskId || ''] || t('agent.activity.task', { name: item.name }) : t('agent.workspace.action.' + (['read', 'write', 'edit', 'bash', 'tool_list', 'delegate'].includes(item.name) ? item.name : 'tool'), { name: item.name })
      const state = activityState(item.state), label = item.name === 'delegate' && state === 'succeeded' ? t('agent.activity.accepted') : t('agent.activity.state.' + state)
      const completed = state === 'succeeded' && item.name !== 'delegate'
      return <Fragment key={item.id}>{heading && <h3>{date ? day === dateKey(now) ? t('agent.workspace.today') : day === dateKey(yesterday) ? t('agent.workspace.yesterday') : new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(date) : t('agent.workspace.timeUnknown')}</h3>}
        <button type="button" className="agent-workspace-entry" data-state={state} onClick={() => item.taskId ? onTask(item.taskId) : setSelected(item.id)}>
          <span className="agent-workspace-entry-icon">{completed ? <CheckIcon size={17} /> : item.kind === 'task' || item.name === 'delegate' ? <BotIcon size={17} /> : item.kind === 'tool' ? <TerminalIcon size={17} /> : <ClockIcon size={17} />}</span>
          <span className="agent-workspace-entry-body"><strong>{title}</strong><span>{label}</span>{date && <time dateTime={date.toISOString()}>{new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(date)}</time>}</span><ChevronRight size={14} />
        </button>
      </Fragment>
    })}
  </div>
}
