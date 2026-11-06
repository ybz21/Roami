import { useEffect, useRef, useState } from 'react'
import { ChevronRight, CopyIcon, CheckIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { isAgentKind } from '../../agent-kind'
import type { AgentTask } from './agent-protocol'
import { taskExecutor, taskInstructions, type TaskSteering } from './agent-task-protocol'
import { useAgentData } from './useAgentData'
import { nativeSessionName } from '../sessions/session-record'

type CapabilityCatalog = {
  skills?: { enabled?: boolean }[]
  cli?: { commands?: { name?: string; enabled?: boolean }[] }[]
  mcp?: { state?: string }[]
}

/** Task body is only one block of the dispatch prompt; steerings append the rest. */
export function appendedInstructions(goal: string, instructions: string) {
  const base = goal.trim(), current = instructions.trim()
  if (!base || !current || current === base || !current.startsWith(base)) return ''
  return current.slice(base.length).replace(/^\s*Additional user requirements:\s*/i, '').trim()
}

export function capabilityCounts(catalog?: CapabilityCatalog) {
  if (!catalog) return null
  const skills = (catalog.skills || []).filter(skill => skill.enabled !== false).length
  const cli = (catalog.cli || []).flatMap(group => group.commands || [])
    .filter(command => command.enabled !== false && !String(command.name || '').startsWith('mcp_')).length
  const mcp = (catalog.mcp || []).filter(server => server.state === 'connected').length
  return { skills, cli, mcp }
}

const shellQuote = (value: string) => /^[\w@%+=:,./-]+$/.test(value) ? value : "'" + value.replace(/'/g, "'\\''") + "'"

function CopyCommand({ command, label }: { command: string; label: string }) {
  const { t } = useI18n()
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const copy = () => {
    void navigator.clipboard?.writeText(command).then(() => {
      setCopied(true)
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setCopied(false), 1500)
    }, () => {})
  }
  return <div className="agent-task-command-block">
    <span className="agent-task-command-label">{label}</span>
    <div className="agent-task-command"><code>{command}</code>
    <button type="button" className="tt-act" aria-label={t('agent.task.copyCommand', { name: label })} onClick={copy}>
      {copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />}
    </button></div>
  </div>
}

export default function TaskDispatch({ task, goal, steering }: { task: AgentTask; goal: string; steering?: TaskSteering | null }) {
  const { t } = useI18n()
  const [dispatch, setDispatch] = useState(false), [tools, setTools] = useState(false)
  const instructions = taskInstructions(task).trim()
  const appended = appendedInstructions(goal, instructions)
  const divergent = !!instructions && !!goal.trim() && !instructions.startsWith(goal.trim()) && instructions !== goal.trim()
  const capabilities = useAgentData<CapabilityCatalog>(tools ? '/agent/capability-settings' : null, 60_000)
  const counts = capabilityCounts(capabilities.value)
  const session = task.nativeSession ? nativeSessionName(task.nativeSession.id) : task.latestAttempt?.sessionId || ''
  const commands = [
    !!session && { label: t('agent.task.commandAttach'), value: 'roami session a ' + shellQuote(session) },
    { label: t('agent.task.commandTrace'), value: 'roami agent trace --task ' + shellQuote(task.id) },
  ].filter((item): item is { label: string; value: string } => !!item)
  const pending = !!steering?.text && steering.state !== 'applied'
  return <>
    {isAgentKind(taskExecutor(task)) && <section className="agent-task-section agent-task-dispatch">
      <button type="button" className="tt-act agent-task-disclosure agent-task-disclosure-row" aria-expanded={dispatch} onClick={() => setDispatch(!dispatch)}>
        <ChevronRight />{t('agent.task.dispatch')}
      </button>
      {dispatch && <>
        <p className="agent-muted">{t('agent.task.dispatchHint')}</p>
        <dl className="agent-task-template">
          <div><dt>{t('agent.task.template.body')}</dt><dd>{t('agent.task.template.bodyDetail')}</dd></div>
          <div><dt>{t('agent.task.template.capabilities')}</dt><dd>{t('agent.task.template.capabilitiesDetail')}</dd></div>
          <div><dt>{t('agent.task.template.delivery')}</dt><dd>{t('agent.task.template.deliveryDetail')}</dd></div>
        </dl>
        {!!appended && <div className="agent-task-delta"><b>{t('agent.task.latestRequirements')}</b><p>{appended}</p></div>}
        {divergent && <div className="agent-task-delta"><b>{t('agent.task.currentDispatch')}</b><p>{instructions}</p></div>}
      </>}
      {pending && <p className="agent-task-note" role="status"><b>{t('agent.task.unappliedRequirements')}</b>{steering.text}</p>}
    </section>}
    <section className="agent-task-section agent-task-tools">
      <button type="button" className="tt-act agent-task-disclosure agent-task-disclosure-row" aria-expanded={tools} onClick={() => setTools(!tools)}>
        <ChevronRight />{t('agent.task.externalTools')}
      </button>
      {tools && <>
        <p className="agent-muted">{t('agent.task.externalToolsHint')}</p>
        {commands.map(item => <CopyCommand key={item.value} command={item.value} label={item.label} />)}
        <p className="agent-task-capabilities"><span>{counts
          ? t('agent.task.capabilitySummary', counts)
          : t('agent.task.capabilitiesAvailable')}</span>
          <a className="tt-act" href="#/capabilities/skills">{t('agent.task.manageCapabilities')}</a>
        </p>
      </>}
    </section>
  </>
}
