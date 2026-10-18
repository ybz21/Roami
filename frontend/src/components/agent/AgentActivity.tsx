import { useState } from 'react'
import { BotIcon, ChevronDown, ChevronRight, ClockIcon, TerminalIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { AgentActivityItem } from './agent-protocol'
import './agent-activity.css'

const active = new Set(['planned', 'running', 'queued', 'preparing', 'starting', 'verifying', 'cancelling'])
const attention = new Set(['failed', 'unknown', 'interrupted'])
const toolNames: Record<string, string> = { session_send: 'send', target_search: 'find', target_resolve: 'resolve', workspace_overview: 'overview', delegate: 'delegate', task_status: 'status', shell: 'shell', memory_search: 'memory', memory_get: 'memory' }
const reasons: Record<string, string> = { CODING_SESSION_TARGET_CONFLICT: 'targetConflict', SESSION_LIFECYCLE_UNAVAILABLE: 'callbacksMissing', SESSION_NOT_IDLE: 'sessionBusy', SESSION_TARGET_NOT_FOUND: 'sessionMissing', TOOL_OUTCOME_UNKNOWN: 'unknownReason', SESSION_TARGET_AMBIGUOUS: 'ambiguous', REMOTE_REQUIRED: 'remoteRequired', CONTEXT_TOO_LARGE: 'contextFull', ROAMI_CLI_AUTH_REQUIRED: 'authRequired' }

export function activityReason(code: string | null | undefined, t: (key: string) => string) {
  return t('agent.activity.' + (code && reasons[code] || 'failedReason'))
}

export default function AgentActivity({ items, onSession }: { items: AgentActivityItem[]; onSession: (id: string) => void }) {
  const { t, locale } = useI18n(), [expanded, setExpanded] = useState(false)
  if (!items.length) return null
  const failed = items.find(item => attention.has(item.state))
  const pending = items.some(item => active.has(item.state))
  const status = failed ? 'failed' : pending ? 'running' : items.some(item => item.state === 'waiting_user') ? 'waiting' : items.some(item => item.state === 'delivered') ? 'delivered' : 'completed'
  const name = (item: AgentActivityItem) => item.kind === 'turn' ? t('agent.activity.reply') : item.kind === 'task' ? t('agent.activity.task', { name: item.name }) : t('agent.activity.' + (toolNames[item.name] || 'tool'), { name: item.name })
  const state = (item: AgentActivityItem) => item.kind === 'task' && item.state === 'failed' && item.external && !item.delivered ? t('agent.activity.notDelivered') : item.kind === 'task' && item.state === 'queued' ? t('agent.activity.queued') : item.name === 'delegate' && item.state === 'succeeded' ? t('agent.activity.accepted') : t('agent.activity.state.' + item.state)
  return <section className={`agent-activity is-${status}`} aria-label={t('agent.activity.title')}>
    <button type="button" className="agent-activity-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
      {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}<span>{t('agent.activity.title')}</span><small>{t('agent.activity.count', { n: items.length })}</small><span className="agent-activity-summary">{t('agent.activity.' + status)}</span>
    </button>
    {failed && <p className="agent-activity-failure" role="status">{state(failed)}{t('agent.activity.separator')}{activityReason(failed.errorCode, t)}</p>}
    {expanded && <ol className="agent-activity-list">{items.map(item => <li key={item.id} className={attention.has(item.state) ? 'is-failed' : ''}>
      {item.kind === 'task' ? <BotIcon size={16} /> : item.name === 'shell' ? <TerminalIcon size={16} /> : <ClockIcon size={16} />}
      <div><div className="agent-activity-step"><span>{name(item)}</span><small>{state(item)}</small></div>
        <time dateTime={new Date(item.startedMs).toISOString()}>{new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(item.startedMs)}{!active.has(item.state) && t('agent.activity.updatedAt', { time: new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(item.updatedMs) })}</time>
        {item.target && <code>{item.target}</code>}
        {item.errorCode && <p>{activityReason(item.errorCode, t)} <code>{item.errorCode}</code></p>}
        {item.taskId && <small className="agent-activity-reference">{t('agent.activity.taskId', { id: item.taskId })}</small>}
        {item.kind === 'task' && item.delivered && item.target && <button type="button" className="tt-act" onClick={() => onSession(item.target!)}>{t('agent.activity.openSession')}</button>}
      </div>
    </li>)}</ol>}
  </section>
}
