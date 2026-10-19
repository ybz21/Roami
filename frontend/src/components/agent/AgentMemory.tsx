import { Fragment, useEffect, useRef, useState } from 'react'
import { App, Button, Input, Modal, Select, Spin, Tabs } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { GearIcon, OpenInIcon } from '../../icons'
import Markdown from '../markdown/Markdown'
import AgentMemoryCard, { type MemoryRecord as Memory } from './AgentMemoryCard'
import './agent-memory.css'

type Evidence = { sourceKey: string; text?: string; unchanged?: boolean; available?: boolean; conversationId?: string; branchId?: string; messageId?: string; kind?: string; createdMs?: number }
type Group = 'all' | 'personal' | 'task' | 'conversation' | 'project' | 'preference'

function today(timezone: string, date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date)
  return ['year', 'month', 'day'].map((name) => parts.find((part) => part.type === name)?.value).join('-')
}

export default function AgentMemory({ cid = '', projects, select, fullPage = false, defaultGroup, compact = false }: { cid?: string; fullPage?: boolean; compact?: boolean; defaultGroup?: Group; projects: { id: string; name: string }[]; select: (cid: string, branch?: string, message?: string) => void }) {
  const { t, locale } = useI18n(), { message, modal } = App.useApp()
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [category, setCategory] = useState<'knowledge' | 'activity'>('knowledge')
  const [group, setGroup] = useState<Group>(defaultGroup || (cid ? 'conversation' : 'all')), [state, setState] = useState('active')
  const [page, setPage] = useState(0), [total, setTotal] = useState(0)
  const [query, setQuery] = useState(''), [project, setProject] = useState(''), [task, setTask] = useState('')
  const [date, setDate] = useState(''), [timezone, setTimezone] = useState('')
  const [tasks, setTasks] = useState<{ id: string; intent_json: string }[]>([]), [items, setItems] = useState<Memory[]>([])
  const [loading, setLoading] = useState(false), [failed, setFailed] = useState(false), [version, setVersion] = useState(0)
  const [busy, setBusy] = useState(''), busyRef = useRef(false)
  const [evidenceTitle, setEvidenceTitle] = useState('')
  const [evidence, setEvidence] = useState<Evidence[] | null>(null), [sourceLoading, setSourceLoading] = useState(false), sourceRequest = useRef(0)
  useEffect(() => {
    const abort = new AbortController()
    setTask(''); setTasks([])
    void api('GET', '/agent/status', undefined, { signal: abort.signal }).then(({ data }) => { if (abort.signal.aborted) return; setTimezone(data.memoryTimezone || 'UTC') }).catch(() => { if (!abort.signal.aborted) setFailed(true) })
    if (cid) void api('GET', '/agent/tasks?conversationId=' + encodeURIComponent(cid), undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) setTasks(data) }).catch(() => {})
    return () => { abort.abort(); sourceRequest.current++ }
  }, [cid])
  useEffect(() => {
    const abort = new AbortController()
    setFailed(false); setItems([]); setTotal(0); setLoading(false)
    if (category === 'knowledge' && ((group === 'project' && !project) || (group === 'task' && !task))) return () => abort.abort()
    const params = new URLSearchParams({ query, state, category, limit: '20', offset: String(page * 20) })
    if (category === 'knowledge' && group === 'personal') params.set('personalOnly', 'true')
    if (category === 'knowledge' && group === 'conversation') params.set('conversationId', cid)
    if (category === 'knowledge' && group === 'task') params.set('taskId', task)
    if (project && (category === 'activity' || group === 'project')) params.set('projectId', project)
    if (category === 'knowledge' && group === 'preference') params.set('kind', 'preference')
    if (category === 'activity' && date) { params.set('dayKey', date); if (timezone) params.set('timezone', timezone) }
    setLoading(true)
    const timer = setTimeout(() => {
      void api('GET', '/agent/memories/catalog?' + params, undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) { setItems(data.items); setTotal(data.total) } }).catch(() => { if (!abort.signal.aborted) setFailed(true) }).finally(() => { if (!abort.signal.aborted) setLoading(false) })
    }, 150)
    return () => { clearTimeout(timer); abort.abort() }
  }, [cid, category, group, query, state, date, timezone, project, task, version, page])
  const mutate = async (item: Memory, method: string, suffix = '', body?: unknown) => {
    if (busyRef.current) return
    busyRef.current = true; setBusy(item.id)
    try { await api(method, '/agent/memories/' + encodeURIComponent(item.id) + suffix, body); setPage(0); setVersion((value) => value + 1) }
    catch { message.error(t('agent.requestFailed')) }
    finally { busyRef.current = false; setBusy('') }
  }
  const sources = async (item: Memory) => {
    const version = ++sourceRequest.current
    setEvidenceTitle(item.title); setEvidence([]); setSourceLoading(true)
    try { const { data } = await api('GET', '/agent/memories/' + encodeURIComponent(item.id) + '/sources'); if (version === sourceRequest.current) setEvidence(data) }
    catch { if (version === sourceRequest.current) { setEvidence(null); message.error(t('agent.requestFailed')) } }
    finally { if (version === sourceRequest.current) setSourceLoading(false) }
  }
  const dayKey = (item: Memory) => category === 'activity' ? item.day_key : compact && item.updated_ms && Number.isFinite(item.updated_ms) && item.updated_ms > 0 ? today(timezone || 'UTC', new Date(item.updated_ms)) : ''
  const changeGroup = (value: Group) => { setGroup(value); setPage(0) }
  return <div className={`agent-memory${fullPage ? ' agent-memory-full' : ''}${compact ? ' agent-memory-compact' : ''}`}>
    {compact ? <div className="agent-memory-toolbar">
      <Select aria-label={t('agent.workspace.memoryView')} value={category} onChange={key => { setCategory(key); setPage(0) }} options={['knowledge', 'activity'].map(key => ({ value: key, label: t('agent.memoryView.' + key) }))} />
      <div><button type="button" className="tt-act" aria-expanded={filtersOpen} data-active={group !== 'all' || state !== 'active' || !!project || !!task || !!date} onClick={() => setFiltersOpen(value => !value)}><GearIcon size={14} />{t('agent.workspace.filters')}</button><a className="tt-act" href="#/settings/agent/memory" aria-label={t('agent.workspace.manageMemory')} title={t('agent.workspace.manageMemory')}><OpenInIcon size={14} /></a></div>
    </div> : <>
      {!fullPage && <div className="agent-memory-entry"><a className="tt-act" href="#/settings/agent/memory">{t('agent.memoryCenter')}</a></div>}
      <Tabs activeKey={category} onChange={key => { setCategory(key as 'knowledge' | 'activity'); setPage(0) }} items={['knowledge', 'activity'].map(key => ({ key, label: t('agent.memoryView.' + key) }))} />
    </>}
    <div className="agent-memory-filters" hidden={compact && !filtersOpen}>
      {category === 'knowledge' && <Select aria-label={t('agent.memoryGroup')} value={group} onChange={changeGroup} options={(['all', 'personal', 'preference', 'project', ...(cid ? ['conversation', 'task'] : [])] as Group[]).map((value) => ({ value, label: t('agent.memoryGroup.' + value), disabled: (value === 'conversation' || value === 'task') && !cid }))} />}
      <Select aria-label={t('agent.memoryState')} value={state} onChange={(value) => { setState(value); setPage(0) }} options={['active', 'candidate', 'conflict'].map((value) => ({ value, label: t('agent.memoryState.' + value) }))} />
      {(group === 'project' || category === 'activity') && <Select aria-label={t('agent.memoryGroup.project')} value={category === 'activity' ? project : project || undefined} placeholder={t('agent.chooseProject')} onChange={(value) => { setProject(value); setPage(0) }} options={[...(category === 'activity' ? [{ value: '', label: t('agent.memoryAllProjects') }] : []), ...projects.map((p) => ({ value: p.id, label: p.name }))]} />}
      {category === 'knowledge' && group === 'task' && <Select aria-label={t('agent.memoryGroup.task')} value={task || undefined} placeholder={t('agent.chooseTask')} onChange={(value) => { setTask(value); setPage(0) }} options={tasks.map((task) => ({ value: task.id, label: JSON.parse(task.intent_json).goal }))} />}
      {category === 'activity' && <><Input type="date" aria-label={t('agent.memoryDate')} value={date} disabled={!timezone} onChange={(e) => { setDate(e.target.value); setPage(0) }} /><button type="button" className="tt-act" disabled={!timezone} onClick={() => { setDate(today(timezone)); setPage(0) }}>{t('agent.memoryToday')}</button>{date && <button type="button" className="tt-act" onClick={() => { setDate(''); setPage(0) }}>{t('agent.memoryAllDates')}</button>}<span className="agent-muted">{timezone}</span></>}
    </div>
    <Input.Search allowClear className="agent-memory-search" aria-label={t('agent.searchMemory')} placeholder={t('agent.searchMemory')} value={query} onChange={(e) => { setQuery(e.target.value); setPage(0) }} maxLength={1000} />
    {loading && <Spin size="small" />}{failed && <p role="alert">{t('agent.requestFailed')} <Button onClick={() => setVersion(value => value + 1)}>{t('agent.retry')}</Button></p>}
    <div className="agent-memory-results-label" role="status">{!loading && !failed && t('agent.memoryTotal', { count: new Intl.NumberFormat(locale).format(total) })}</div>
    <div className="agent-memory-list" aria-busy={loading}>{!items.length && !loading && !failed && <div className="agent-memory-empty"><strong>{t(category === 'knowledge' ? 'agent.noMemories' : 'agent.memoryNoActivity')}</strong><p>{t(category === 'knowledge' ? 'agent.memoryEmptyHint' : 'agent.memoryActivityEmptyHint')}</p></div>}{items.map((item, index) => <Fragment key={item.id}>
      {(compact || category === 'activity') && dayKey(item) && dayKey(item) !== (items[index - 1] ? dayKey(items[index - 1]) : '') && <h3 className="agent-memory-day-heading">{dayKey(item) === today(timezone || 'UTC') ? t('agent.workspace.today') : dayKey(item)}</h3>}
      <AgentMemoryCard compact={compact} item={item} projects={projects} timezone={timezone} busy={!!busy} sources={() => { void sources(item) }} mutate={action => { if (action === 'delete') void mutate(item, 'DELETE', '?forgetSources=false'); else void mutate(item, 'POST', '/confirm', { accepted: action === 'confirm' }) }} forget={() => modal.confirm({ title: t('agent.memoryForgetTitle'), content: t('agent.memoryForgetBody'), okText: t('agent.memoryForget'), cancelText: t('common.cancel'), onOk: () => mutate(item, 'DELETE', '?forgetSources=true') })} />
    </Fragment>)}</div>
    {!loading && !failed && (!compact || total > 0) && <div className="agent-memory-pagination"><span>{t('agent.memoryPage', { page: page + 1 })}</span><Button disabled={page === 0} onClick={() => setPage(value => value - 1)}>{t('agent.memoryPrevious')}</Button><Button disabled={(page + 1) * 20 >= total} onClick={() => setPage(value => value + 1)}>{t('agent.memoryNext')}</Button></div>}
    {compact && <details className="agent-memory-catalog-note"><summary>{t('agent.workspace.aboutMemory')}</summary><p>{t('agent.workspace.memoryHint')}</p></details>}
    <Modal destroyOnClose open={evidence !== null} title={t('agent.memorySourcesFor', { title: evidenceTitle })} footer={null} onCancel={() => { sourceRequest.current++; setEvidence(null); setSourceLoading(false) }}>
      {sourceLoading && <Spin size="small" />}<div className="agent-memory agent-memory-evidence">{evidence?.map((source) => <article className="agent-memory-card" key={source.sourceKey}>{source.available === false ? <p>{t('agent.memorySourceMissing')}</p> : <>{source.kind && <b>{t('agent.memorySource.' + source.kind)}</b>}{source.createdMs && <time className="agent-muted">{new Date(source.createdMs).toLocaleString(locale, { timeZone: timezone || 'UTC' })}</time>}<Markdown>{source.text || ''}</Markdown>{source.unchanged === false && <p className="agent-muted">{t('agent.memorySourceChanged')}</p>}{source.conversationId && <Button onClick={() => select(source.conversationId!, source.branchId, source.messageId)}>{t('agent.memoryOpenSource')}</Button>}</>}</article>)}</div>
    </Modal>
  </div>
}
