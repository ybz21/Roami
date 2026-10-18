import { useState } from 'react'
import { BotIcon, ChevronDown, ChevronRight, ClockIcon, TerminalIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { AgentActivityItem } from './agent-protocol'
import './agent-activity.css'

const active = new Set(['planned', 'running', 'queued', 'preparing', 'starting', 'verifying', 'cancelling'])
const attention = new Set(['failed', 'unknown', 'interrupted'])
const toolNames: Record<string, string> = { session_send: 'send', target_search: 'find', target_resolve: 'resolve', workspace_overview: 'overview', delegate: 'delegate', task_status: 'status', shell: 'shell', memory_search: 'memory', memory_get: 'memory' }
const reasons: Record<string, string> = { COMMAND_EXIT_NONZERO: 'commandFailed', CODING_SESSION_TARGET_CONFLICT: 'targetConflict', SESSION_LIFECYCLE_UNAVAILABLE: 'callbacksMissing', SESSION_NOT_IDLE: 'sessionBusy', SESSION_TARGET_NOT_FOUND: 'sessionMissing', TOOL_OUTCOME_UNKNOWN: 'unknownReason', SESSION_TARGET_AMBIGUOUS: 'ambiguous', REMOTE_REQUIRED: 'remoteRequired', CONTEXT_TOO_LARGE: 'contextFull', ROAMI_CLI_AUTH_REQUIRED: 'authRequired' }

export function activityReason(code: string | null | undefined, t: (key: string) => string) {
  return t('agent.activity.' + (code && reasons[code] || 'failedReason'))
}

const knownStates = new Set([...active, ...attention, 'succeeded', 'cancelled', 'waiting_user', 'accepted', 'delivered'])
export function activityState(state: string) { return knownStates.has(state) ? state : 'unknown' }

export default function AgentActivity({ items, onSession }: { items: AgentActivityItem[]; onSession: (id: string) => void }) {
  return <>{items.map(item => <ActivityStep key={item.id} item={item} onSession={onSession} />)}</>
}

function ActivityStep({ item, onSession }: { item: AgentActivityItem; onSession: (id: string) => void }) {
  const { t, locale } = useI18n(), [expanded, setExpanded] = useState(false)
  const status = activityState(item.state)
  const name = item.kind === 'turn' ? t('agent.activity.reply') : item.kind === 'task' ? t('agent.activity.task', { name: item.name }) : t('agent.activity.' + (toolNames[item.name] || 'tool'), { name: item.name })
  const state = item.kind === 'task' && status === 'failed' && item.external && !item.delivered ? t('agent.activity.notDelivered') : item.name === 'delegate' && status === 'succeeded' ? t('agent.activity.accepted') : t('agent.activity.state.' + status)
  const formatTime = (ms: number) => new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(ms)
  const failed = attention.has(status)
  return <section className={`agent-activity is-${active.has(status) ? 'running' : failed ? 'failed' : status}`} aria-label={t('agent.activity.title')} data-activity-id={item.id} data-state={status}>
    <button type="button" className="agent-activity-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
      {item.kind === 'task' ? <BotIcon size={16} /> : item.name === 'shell' ? <TerminalIcon size={16} /> : <ClockIcon size={16} />}
      <span className="agent-activity-name">{name}<small>{item.name}</small></span><span className="agent-activity-summary">{state}</span>{expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
    </button>
    <time dateTime={new Date(item.startedMs).toISOString()}>{formatTime(item.startedMs)}{!active.has(status) && t('agent.activity.updatedAt', { time: formatTime(item.updatedMs) })}</time>
    {failed && <p className="agent-activity-failure" role="status">{state}{t('agent.activity.separator')}{status === 'unknown' ? t('agent.activity.outcomeUnknown') : activityReason(item.errorCode, t)}</p>}
    {expanded && <div className="agent-activity-details">
      {item.target && <code>{item.target}</code>}
      {item.errorCode && <p>{activityReason(item.errorCode, t)} <code>{item.errorCode}</code></p>}
      {item.taskId && <small className="agent-activity-reference">{t('agent.activity.taskId', { id: item.taskId })}</small>}
      {item.kind === 'task' && item.delivered && item.target && <button type="button" className="tt-act" onClick={() => onSession(item.target!)}>{t('agent.activity.openSession')}</button>}
    </div>}
  </section>
}
