import { memo, useEffect, useState } from 'react'
import { api } from '../../api'
import { BotIcon, ChevronDown, ChevronRight, ClockIcon, TerminalIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { AgentActivityItem } from './agent-protocol'
import './agent-activity.css'

const active = new Set(['planned', 'running', 'queued', 'preparing', 'starting', 'verifying', 'cancelling'])
const attention = new Set(['failed', 'unknown', 'interrupted'])
const toolNames: Record<string, string> = { session_send: 'send', target_search: 'find', target_resolve: 'resolve', workspace_overview: 'overview', delegate: 'delegate', task_status: 'status', shell: 'shell', memory_search: 'memory', memory_get: 'memory', browser_open: 'browserOpen', browser_act: 'browserAct', browser_observe: 'browserObserve' }
const reasons: Record<string, string> = { MODEL_DEADLINE: 'modelTimeout', AGENT_TURN_DEADLINE: 'turnTimeout', COMMAND_EXIT_NONZERO: 'commandFailed', CODING_SESSION_TARGET_CONFLICT: 'targetConflict', SESSION_LIFECYCLE_UNAVAILABLE: 'callbacksMissing', SESSION_NOT_IDLE: 'sessionBusy', SESSION_TARGET_NOT_FOUND: 'sessionMissing', TOOL_OUTCOME_UNKNOWN: 'unknownReason', SESSION_TARGET_AMBIGUOUS: 'ambiguous', REMOTE_REQUIRED: 'remoteRequired', CONTEXT_TOO_LARGE: 'contextFull', ROAMI_CLI_AUTH_REQUIRED: 'authRequired' }

export function activityReason(code: string | null | undefined, t: (key: string) => string) {
  return t('agent.activity.' + (code && reasons[code] || 'failedReason'))
}

const knownStates = new Set([...active, ...attention, 'succeeded', 'cancelled', 'waiting_user', 'accepted', 'delivered'])
export function activityState(state: string) { return knownStates.has(state) ? state : 'unknown' }

type ActivityProps = { items: AgentActivityItem[]; onSession: (id: string) => void; conversationId?: string; branchId?: string; taskScope?: string; record?: boolean }
function AgentActivity({ items, onSession, conversationId, branchId, taskScope, record = false }: ActivityProps) {
  const { t } = useI18n(), [expanded, setExpanded] = useState(false)
  const steps = items.map(item => <ActivityStep key={item.id} item={item} onSession={onSession} conversationId={conversationId} branchId={branchId} taskScope={taskScope} />)
  if (record) return <div className="agent-task-tool-steps">{steps}</div>
  if (items.length < 2) return <>{steps}</>
  const routed = [...items].reverse().find(item => item.routingDecision)?.routingDecision
  const latest = items[items.length - 1], problems = items.filter(item => attention.has(activityState(item.state))).length
  return <section className="agent-activity-group" aria-label={t('agent.activity.title')}>
    <button type="button" className="agent-activity-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
      <TerminalIcon size={16} /><span className="agent-activity-name">{t('agent.activity.group', { count: items.length })}<small>{latest.name}</small></span>
      {problems > 0 && <span className="agent-activity-failure">{t('agent.activity.problems', { count: problems })}</span>}
      <span className="agent-activity-summary">{items.some(item => active.has(item.state)) ? t('agent.activity.state.running') : problems ? t('agent.activity.needsAttention') : t('agent.activity.finished')}</span>{expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
    </button>
    {!expanded && routed && <p className="agent-routing-reason">{t('agent.routing.reason')}{t('agent.activity.separator')}{routed.routingExplanation}</p>}
    {expanded && <div className="agent-activity-group-steps">{steps}</div>}
  </section>
}

function ActivityStep({ item, onSession, conversationId, branchId, taskScope }: { item: AgentActivityItem; onSession: (id: string) => void; conversationId?: string; branchId?: string; taskScope?: string }) {
  const { t, locale } = useI18n(), [expanded, setExpanded] = useState(false)
  const status = activityState(item.state)
  const name = item.kind === 'turn' ? t('agent.activity.reply') : item.kind === 'task' ? t('agent.activity.task', { name: item.name }) : t('agent.activity.' + (toolNames[item.name] || 'tool'), { name: item.name })
  const state = item.kind === 'task' && status === 'failed' && item.external && !item.delivered ? t('agent.activity.notDelivered') : item.name === 'delegate' && status === 'succeeded' ? t('agent.activity.accepted') : t('agent.activity.state.' + status)
  const formatTime = (ms: number) => new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(ms)
  const failed = attention.has(status)
  return <section className={`agent-activity is-${active.has(status) ? 'running' : failed ? 'failed' : status}`} aria-label={t('agent.activity.title')} data-activity-id={item.id} data-state={status}>
    <button type="button" className="agent-activity-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
      {item.kind === 'task' ? <BotIcon size={16} /> : item.name === 'shell' ? <TerminalIcon size={16} /> : <ClockIcon size={16} />}
      <span className="agent-activity-name">{name}</span><time dateTime={new Date(item.startedMs).toISOString()}>{formatTime(item.startedMs)}</time><span className="agent-activity-summary">{state}</span>{expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
    </button>
    {failed && <p className="agent-activity-failure" role="status">{state}{t('agent.activity.separator')}{status === 'unknown' ? t('agent.activity.outcomeUnknown') : activityReason(item.errorCode, t)}</p>}
    {item.routingDecision && <p className="agent-routing-reason">{t('agent.routing.reason')}{t('agent.activity.separator')}{item.routingDecision.routingExplanation}</p>}
    {expanded && <div className="agent-activity-details">
      <p className="agent-activity-reference">{t('agent.activity.startedAt', { time: formatTime(item.startedMs) })}{t('agent.activity.updatedAt', { time: formatTime(item.updatedMs) })}</p>
      {(conversationId || taskScope) && <ActivityPayload conversationId={conversationId || ''} branchId={branchId} taskScope={taskScope} item={item} />}
      {item.routingDecision && <div className="agent-routing-details">
        <p>{t('agent.routing.complexity')}{t('agent.activity.separator')}{t(item.routingDecision.complexity === 'complex' ? 'agent.routing.complex' : item.routingDecision.complexity === 'bounded' ? 'agent.routing.bounded' : 'agent.routing.unknown')}</p>
        <p>{t('agent.routing.policy', { version: item.routingDecision.policyVersion })}</p>
        {Object.entries(item.routingDecision.complexityBasis || {}).map(([key, value]) => <p key={key}>{value}</p>)}
        {item.routingDecision.capabilityVerification && <p>{t('agent.routing.capabilitiesUnverified')}</p>}
      </div>}
      {item.kind === 'tool' && <code>{item.name}</code>}
      {item.target && <code>{item.target}</code>}
      {item.errorCode && <p>{activityReason(item.errorCode, t)} <code>{item.errorCode}</code></p>}
      {item.taskId && <small className="agent-activity-reference">{t('agent.activity.taskId', { id: item.taskId })}</small>}
      {item.kind === 'task' && item.delivered && item.target && <button type="button" className="tt-act" onClick={() => onSession(item.target!)}>{t('agent.activity.openSession')}</button>}
    </div>}
  </section>
}


type PayloadPreview = { text: string; truncated: boolean }
type ActivityDetail = { id: string; state: string; input: PayloadPreview; output: PayloadPreview | null }
function ActivityPayload({ conversationId, branchId, taskScope, item }: { conversationId: string; branchId?: string; taskScope?: string; item: AgentActivityItem }) {
  const { t } = useI18n(), [detail, setDetail] = useState<ActivityDetail | null>(null), [failed, setFailed] = useState(false), [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const abort = new AbortController()
    setDetail(null); setFailed(false)
    void api('GET', taskScope ? `/agent/tasks/${encodeURIComponent(taskScope)}/activities/${encodeURIComponent(item.id)}` : `/agent/conversations/${encodeURIComponent(conversationId)}/activities/${encodeURIComponent(item.id)}${branchId ? `?branchId=${encodeURIComponent(branchId)}` : ''}`, undefined, { signal: abort.signal })
      .then(({ data }) => { if (!abort.signal.aborted) setDetail(data) })
      .catch(() => { if (!abort.signal.aborted) setFailed(true) })
    return () => abort.abort()
  }, [conversationId, branchId, item.id, item.updatedMs, item.state, attempt, taskScope])
  if (failed) return <div role="alert">{t('agent.activity.detailsUnavailable')} <button type="button" className="tt-act" onClick={() => setAttempt(attempt + 1)}>{t('agent.retry')}</button></div>
  if (!detail) return <p role="status">{t('agent.activity.loadingDetails')}</p>
  return <div className="agent-activity-payloads">{(['input', 'output'] as const).map(kind => <details key={kind} open={kind === 'output'}><summary>{t(`agent.activity.${kind}`)}</summary>{detail[kind] ? <><pre>{detail[kind]!.text}</pre>{detail[kind]!.truncated && <p>{t('agent.activity.previewTruncated')}</p>}</> : <p>{t('agent.activity.noOutput')}</p>}</details>)}</div>
}

export default memo(AgentActivity)
