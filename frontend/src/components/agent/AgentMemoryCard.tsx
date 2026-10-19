import { useState } from 'react'
import { App, Dropdown } from 'antd'
import { MoreIcon, NotebookIcon, ClockIcon } from '../../icons'
import { useI18n } from '../../i18n'
import Markdown from '../markdown/Markdown'

export type MemoryRecord = { id: string; title: string; body: string; state: string; kind?: string; project_id?: string; conversation_id?: string; conversation_title?: string; task_id?: string; task_title?: string; day_key?: string; timezone?: string; updated_ms?: number; source_count?: number }
export function dailyMemory(item: MemoryRecord): { counts: Record<string, number>; scopeKey?: string } | null {
  if (!item.day_key) return null
  try { const value = JSON.parse(item.body); return value && typeof value.counts === 'object' && value.counts !== null ? value : null } catch { return null }
}

export default function AgentMemoryCard({ item, projects, timezone, busy, sources, mutate, forget, compact = false }: { item: MemoryRecord; compact?: boolean; projects: { id: string; name: string }[]; timezone: string; busy: boolean; sources: () => void; mutate: (action: 'delete' | 'confirm' | 'reject') => void; forget: () => void }) {
  const { t, locale } = useI18n(), [expanded, setExpanded] = useState(false), daily = dailyMemory(item)
  const { modal } = App.useApp()
  const remove = () => modal.confirm({
    title: t('agent.memoryDelete'), content: t('agent.memoryDeleteConfirm'),
    okText: t('agent.memoryDelete'), cancelText: t('common.cancel'), okButtonProps: { danger: true },
    onOk: () => mutate('delete'),
  })
  const projectId = item.project_id || daily?.scopeKey
  const title = item.day_key ? projects.find(project => project.id === projectId)?.name || (!projectId || projectId === 'unassigned' ? t('agent.memoryUnassigned') : projectId) : item.title
  const date = item.updated_ms ? new Date(item.updated_ms) : null
  const actions = item.state === 'active' ? [{ key: 'delete', label: t('agent.memoryDelete'), danger: true }, { key: 'forget', label: t('agent.memoryForget'), danger: true }] : [{ key: 'confirm', label: t('agent.memoryConfirm') }, { key: 'reject', label: t('agent.memoryReject') }]
  return <article className={`agent-memory-card${daily ? ' is-daily' : ''}${compact ? ' agent-memory-record' : ''}`}>
    {compact && <span className="agent-memory-record-icon" aria-hidden="true">{daily ? <ClockIcon size={20} /> : <NotebookIcon size={20} />}</span>}
    <div className="agent-memory-card-heading">{compact ? <h3>{title}</h3> : <div className="agent-memory-meta"><span className="agent-memory-kind">{t(item.day_key ? 'agent.memoryView.activity' : 'agent.memoryKind.' + (item.kind || 'fact'))}</span><span className="agent-memory-tag" data-state={item.state}>{t('agent.memoryState.' + item.state)}</span></div>}<Dropdown trigger={['click']} menu={{ items: actions, onClick: ({ key }) => { if (key === 'forget') forget(); else if (key === 'delete') remove(); else mutate(key as 'confirm' | 'reject') } }}><button type="button" className="tt-act" disabled={busy} aria-label={t('agent.memoryMore', { title })}><MoreIcon size={16} /></button></Dropdown></div>
    {!compact && <h3>{title}</h3>}
    {daily ? <div className="agent-memory-counts">{['userTurns', 'tasksCreated', 'tasksCompleted', 'tasksFailed', 'tasksCancelled', 'tasksInterrupted'].map(key => <div key={key} data-kind={key} className={daily.counts[key] > 0 ? 'has-count' : undefined}><strong>{Number.isFinite(daily.counts[key]) ? new Intl.NumberFormat(locale).format(daily.counts[key]) : t('agent.memoryCountUnknown')}</strong><span>{t('agent.count.' + key)}</span></div>)}</div> : expanded ? <div className="agent-memory-content"><Markdown>{item.body}</Markdown></div> : <p className="agent-memory-body-preview">{item.body}</p>}
    <div className="agent-memory-scopes">
      {compact && <><span className="agent-memory-kind">{t(item.day_key ? 'agent.memoryView.activity' : 'agent.memoryKind.' + (item.kind || 'fact'))}</span>{item.state !== 'active' && <span className="agent-memory-tag" data-state={item.state}>{t('agent.memoryState.' + item.state)}</span>}</>}
      {!item.project_id && !item.conversation_id && !item.task_id && !item.day_key && <span>{t('agent.memoryGroup.personal')}</span>}
      {item.project_id && <span>{t('agent.memoryScope.project', { name: projects.find(project => project.id === item.project_id)?.name || item.project_id })}</span>}
      {item.conversation_id && <span>{t('agent.memoryScope.conversation', { name: item.conversation_title || item.conversation_id })}</span>}
      {item.task_id && <span>{t('agent.memoryScope.task', { name: item.task_title || item.task_id })}</span>}
      {item.day_key && <span>{item.timezone || 'UTC'}</span>}
    </div>
    {!compact && <div className="agent-memory-card-bottom">{date && <time dateTime={date.toISOString()} title={date.toLocaleString(locale, { timeZone: timezone || 'UTC' })}>{t('agent.memoryUpdated', { date: new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: timezone || 'UTC', timeZoneName: 'short' }).format(date) })}</time>}<span>{item.source_count === undefined ? t('agent.memorySourceUnknown') : t('agent.memorySourceCount', { count: item.source_count })}</span></div>}
    <div className="agent-memory-actions"><button type="button" className="tt-act" onClick={sources} aria-label={t('agent.memorySources')}>{t('agent.memorySources')}{compact && item.source_count !== undefined && <span className="agent-memory-source-count" aria-hidden="true">{new Intl.NumberFormat(locale).format(item.source_count)}</span>}</button>{!daily && <button type="button" className="tt-act" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{t(expanded ? 'agent.memoryCollapse' : 'agent.memoryExpand')}</button>}{item.state !== 'active' && <button type="button" className="tt-act ok" disabled={busy} onClick={() => mutate('confirm')}>{t('agent.memoryConfirm')}</button>}{compact && date && <time className="agent-memory-record-date" dateTime={date.toISOString()} title={date.toLocaleString(locale, { timeZone: timezone || 'UTC' })}>{new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', timeZone: timezone || 'UTC' }).format(date)}</time>}</div>
  </article>
}
