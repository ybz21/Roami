import { useState } from 'react'
import { Segmented, Select, Spin } from 'antd'
import { useI18n } from '../../i18n'
import { currentNodeId } from '../cluster/node-url'
import { openAgentPage } from './agent-page-route'
import AgentActivity from './AgentActivity'
import AgentMessageView from './AgentMessageView'
import { TaskResult } from './TaskOutput'
import { useAgentData } from './useAgentData'
import type { AgentActivityItem, AgentSnapshot } from './agent-protocol'
import type { TaskArtifact, TaskAttempt } from './agent-task-protocol'

export default function AgentTaskRecord({ id, active, attempts, truncated, artifacts, onPreview, onSession, onAnswer, canAnswer }: {
  id: string; active: boolean; attempts: TaskAttempt[]; truncated: boolean; artifacts: TaskArtifact[]
  onPreview: (id: string) => void; onSession: (id: string) => void; onAnswer: (text: string) => Promise<boolean>; canAnswer: boolean
}) {
  const { t, locale } = useI18n(), [tab, setTab] = useState<string | null>(null)
  const native = attempts.filter(attempt => attempt.hasConversation)
  const selected = tab || (native.length ? 'process' : 'reports')
  return <div className="agent-task-record">
    <Segmented block value={selected} onChange={value => setTab(String(value))} options={[
      { value: 'process', label: t('agent.task.process') },
      ...(native.length ? [{ value: 'conversation', label: t('agent.task.conversation') }] : []),
      { value: 'reports', label: t('agent.task.reports') },
    ]} />
    {selected === 'process' && <TaskProcess id={id} active={active} onSession={onSession} />}
    {selected === 'conversation' && <TaskConversation id={id} active={active} attempts={native} currentRun={attempts[0]?.id} onAnswer={onAnswer} canAnswer={canAnswer} />}
    {selected === 'reports' && <>
      {!active && <p className="agent-muted">{t('agent.task.archivedRecord')}</p>}
      {attempts.map(attempt => <div className="agent-task-attempt" key={attempt.id}><b>{t('agent.task.revision', { n: attempt.revision })}</b><span>{t('agent.state.' + attempt.state)}</span>{attempt.finishedMs && <time>{new Date(attempt.finishedMs).toLocaleString(locale)}</time>}<div className="agent-task-attempt-record"><TaskResult attempt={attempt} artifacts={artifacts} onPreview={onPreview} /></div></div>)}
      {truncated && <small className="agent-muted">{t('agent.task.moreHistory')}</small>}
    </>}
  </div>
}

export function TaskProcess({ id, active, onSession }: { id: string; active: boolean; onSession: (id: string) => void }) {
  const { t } = useI18n()
  const data = useAgentData<AgentActivityItem[]>('/agent/tasks/' + encodeURIComponent(id) + '/activities', 0, active ? 3000 : 0)
  const steps = (data.value || []).filter(item => item.kind === 'tool' || item.parentTaskId)
  return <>
    <button type="button" className="tt-act" onClick={() => openAgentPage('debug', 'task:' + id)}>{t('agent.task.viewTrace')}</button>
    {data.failed && <p role="alert">{t('agent.activity.detailsUnavailable')} <button type="button" className="tt-act" onClick={data.refresh}>{t('agent.retry')}</button></p>}
    {data.loading && <Spin size="small" />}
    {!!steps.length && <AgentActivity record items={steps} taskScope={id} onSession={onSession} />}
    {!data.loading && !data.failed && !steps.length && <p className="agent-muted">{t('agent.task.noProcess')}</p>}
  </>
}

function TaskConversation({ id, active, attempts, currentRun, onAnswer, canAnswer }: { id: string; active: boolean; attempts: TaskAttempt[]; currentRun?: string; onAnswer: (text: string) => Promise<boolean>; canAnswer: boolean }) {
  const { t } = useI18n(), [selection, select] = useState(''), [shown, show] = useState(24)
  const run = attempts.find(item => item.id === selection) || attempts[0]
  const current = run?.id === currentRun, reading = active && current && !run?.finishedMs
  const data = useAgentData<AgentSnapshot>(run ? '/agent/tasks/' + encodeURIComponent(id) + '/conversation?runId=' + encodeURIComponent(run.id) : null, 0, reading ? 3000 : 0)
  const messages = (data.value?.messages || []).filter(item => ['user', 'assistant'].includes(item.role) && (item.content.text || item.content.question || item.content.attachments?.length || item.status === 'streaming'))
  const latestUser = messages.reduce((seq, item) => item.role === 'user' ? Math.max(seq, item.seq) : seq, 0)
  return <>
    {attempts.length > 1 && <Select aria-label={t('agent.task.execution')} value={run?.id} onChange={value => { select(value); show(24) }} options={attempts.map((item, index) => ({ value: item.id, label: t('agent.task.executionNumber', { n: item.attemptNo ?? attempts.length - index }) }))} />}
    {data.loading && <Spin size="small" />}
    {data.failed && <p role="alert">{t('agent.activity.detailsUnavailable')} <button type="button" className="tt-act" onClick={data.refresh}>{t('agent.retry')}</button></p>}
    {messages.length > shown && <button type="button" className="tt-act" onClick={() => show(shown + 24)}>{t('agent.task.moreConversation')}</button>}
    <div className="agent-task-conversation">{messages.slice(-shown).map(item => <AgentMessageView key={item.id} item={item} node={currentNodeId()} readOnly focused={false} remember={() => {}} canAnswer={canAnswer && current && item.seq > latestUser} answer={onAnswer} />)}</div>
    {!data.loading && !data.failed && !messages.length && <p className="agent-muted">{t('agent.task.noConversation')}</p>}
  </>
}
