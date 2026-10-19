import { useEffect, useRef, useState } from 'react'
import { App, Button, Input, Modal, Select, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import Markdown from '../markdown/Markdown'
import './agent-memory.css'

type Memory = { id: string; title: string; body: string; state: string; kind?: string; project_id?: string; conversation_id?: string; conversation_title?: string; task_id?: string; task_title?: string; day_key?: string; timezone?: string; updated_ms?: number; source_count?: number }
type Evidence = { sourceKey: string; text?: string; unchanged?: boolean; available?: boolean; conversationId?: string; branchId?: string; messageId?: string; kind?: string; createdMs?: number }
type Group = 'all' | 'personal' | 'day' | 'task' | 'conversation' | 'project' | 'preference'

function today(timezone: string) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  return ['year', 'month', 'day'].map((name) => parts.find((part) => part.type === name)?.value).join('-')
}

export default function AgentMemory({ cid = '', projects, select, fullPage = false }: { cid?: string; fullPage?: boolean; projects: { id: string; name: string }[]; select: (cid: string, branch?: string, message?: string) => void }) {
  const { t, locale } = useI18n(), { message, modal } = App.useApp()
  const [group, setGroup] = useState<Group>(cid ? 'conversation' : 'all'), [state, setState] = useState('active')
  const [page, setPage] = useState(0), [total, setTotal] = useState(0)
  const [query, setQuery] = useState(''), [project, setProject] = useState(''), [task, setTask] = useState('')
  const [date, setDate] = useState(''), [timezone, setTimezone] = useState('')
  const [tasks, setTasks] = useState<{ id: string; intent_json: string }[]>([]), [items, setItems] = useState<Memory[]>([])
  const [loading, setLoading] = useState(false), [failed, setFailed] = useState(false), [version, setVersion] = useState(0)
  const [busy, setBusy] = useState(''), busyRef = useRef(false)
  const [evidence, setEvidence] = useState<Evidence[] | null>(null), [sourceLoading, setSourceLoading] = useState(false), sourceRequest = useRef(0)
  useEffect(() => {
    const abort = new AbortController()
    setTask(''); setTasks([])
    void api('GET', '/agent/status', undefined, { signal: abort.signal }).then(({ data }) => { if (abort.signal.aborted) return; setTimezone(data.memoryTimezone || 'UTC'); setDate(today(data.memoryTimezone || 'UTC')) }).catch(() => { if (!abort.signal.aborted) setFailed(true) })
    if (cid) void api('GET', '/agent/tasks?conversationId=' + encodeURIComponent(cid), undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) setTasks(data) }).catch(() => {})
    return () => { abort.abort(); sourceRequest.current++ }
  }, [cid])
  useEffect(() => {
    const abort = new AbortController()
    setFailed(false); setItems([]); setTotal(0); setLoading(false)
    if ((group === 'day' && (!date || !timezone)) || (group === 'project' && !project) || (group === 'task' && !task)) return () => abort.abort()
    const params = new URLSearchParams({ query, state, limit: '20', offset: String(page * 20) })
    if (group === 'personal') params.set('personalOnly', 'true')
    if (group === 'conversation') params.set('conversationId', cid)
    if (group === 'task') params.set('taskId', task)
    if (group === 'project') params.set('projectId', project)
    if (group === 'preference') params.set('kind', 'preference')
    if (group === 'day') { params.set('dayKey', date); params.set('timezone', timezone) }
    setLoading(true)
    const timer = setTimeout(() => {
      void api('GET', '/agent/memories/catalog?' + params, undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) { setItems(data.items); setTotal(data.total) } }).catch(() => { if (!abort.signal.aborted) setFailed(true) }).finally(() => { if (!abort.signal.aborted) setLoading(false) })
    }, 150)
    return () => { clearTimeout(timer); abort.abort() }
  }, [cid, group, query, state, date, timezone, project, task, version, page])
  const mutate = async (item: Memory, method: string, suffix = '', body?: unknown) => {
    if (busyRef.current) return
    busyRef.current = true; setBusy(item.id)
    try { await api(method, '/agent/memories/' + encodeURIComponent(item.id) + suffix, body); setPage(0); setVersion((value) => value + 1) }
    catch { message.error(t('agent.requestFailed')) }
    finally { busyRef.current = false; setBusy('') }
  }
  const sources = async (item: Memory) => {
    const version = ++sourceRequest.current
    setEvidence([]); setSourceLoading(true)
    try { const { data } = await api('GET', '/agent/memories/' + encodeURIComponent(item.id) + '/sources'); if (version === sourceRequest.current) setEvidence(data) }
    catch { if (version === sourceRequest.current) { setEvidence(null); message.error(t('agent.requestFailed')) } }
    finally { if (version === sourceRequest.current) setSourceLoading(false) }
  }
  const body = (item: Memory) => {
    if (!item.day_key) return <p>{item.body}</p>
    try {
      const value = JSON.parse(item.body)
      if (!value.counts) return <p>{item.body}</p>
      return <><b>{projects.find((p) => p.id === value.scopeKey)?.name || (value.scopeKey === 'unassigned' ? t('agent.memoryUnassigned') : value.scopeKey)}</b><div className="agent-memory-counts">{['userTurns', 'tasksCreated', 'tasksCompleted', 'tasksFailed', 'tasksCancelled', 'tasksInterrupted'].map((key) => <span key={key}>{t('agent.count.' + key)} <strong>{new Intl.NumberFormat(locale).format(value.counts[key] || 0)}</strong></span>)}</div></>
    } catch { return <p>{item.body}</p> }
  }
  const changeGroup = (value: Group) => { setGroup(value); setPage(0) }
  return <div className={`agent-memory${fullPage ? ' agent-memory-full' : ''}`}>
    {!fullPage && <div className="agent-memory-entry"><a className="tt-act" href="#/settings/agent/memory">{t('agent.memoryCenter')}</a></div>}
    <div className="agent-memory-filters">
      <Select aria-label={t('agent.memoryGroup')} value={group} onChange={changeGroup} options={(['all', 'personal', 'preference', 'project', 'day', ...(cid ? ['conversation', 'task'] : [])] as Group[]).map((value) => ({ value, label: t('agent.memoryGroup.' + value), disabled: (value === 'conversation' || value === 'task') && !cid }))} />
      <Select aria-label={t('agent.memoryState')} value={state} onChange={(value) => { setState(value); setPage(0) }} options={['active', 'candidate', 'conflict'].map((value) => ({ value, label: t('agent.memoryState.' + value) }))} />
      {group === 'project' && <Select aria-label={t('agent.memoryGroup.project')} value={project || undefined} placeholder={t('agent.chooseProject')} onChange={(value) => { setProject(value); setPage(0) }} options={projects.map((p) => ({ value: p.id, label: p.name }))} />}
      {group === 'task' && <Select aria-label={t('agent.memoryGroup.task')} value={task || undefined} placeholder={t('agent.chooseTask')} onChange={(value) => { setTask(value); setPage(0) }} options={tasks.map((task) => ({ value: task.id, label: JSON.parse(task.intent_json).goal }))} />}
      {group === 'day' && <><Input type="date" aria-label={t('agent.memoryDate')} value={date} disabled={!timezone} onChange={(e) => { setDate(e.target.value); setPage(0) }} /><span className="agent-muted">{timezone}</span></>}
    </div>
    <Input.Search className="agent-memory-search" aria-label={t('agent.searchMemory')} placeholder={t('agent.searchMemory')} value={query} onChange={(e) => { setQuery(e.target.value); setPage(0) }} maxLength={1000} />
    {loading && <Spin size="small" />}{failed && <p role="alert">{t('agent.requestFailed')}</p>}
    <div className="agent-memory-list" aria-busy={loading}>{!items.length && !loading && !failed && <p className="agent-muted">{t('agent.noMemories')}</p>}{items.map((item) => <article className="agent-memory-card" key={item.id}>
      <div className="agent-memory-meta"><span className="agent-memory-tag" data-state={item.state}>{t('agent.memoryState.' + item.state)}</span>{item.kind && <span>{t('agent.memoryKind.' + item.kind)}</span>}{item.updated_ms && <time dateTime={new Date(item.updated_ms).toISOString()}>{new Date(item.updated_ms).toLocaleString(locale, { timeZone: timezone || 'UTC' })}</time>}</div>
      <b>{item.day_key || item.title}</b>{body(item)}
      <div className="agent-memory-scopes">
        {!item.project_id && !item.conversation_id && !item.task_id && !item.day_key && <span>{t('agent.memoryGroup.personal')}</span>}
        {item.project_id && <span>{t('agent.memoryScope.project', { name: projects.find(p => p.id === item.project_id)?.name || item.project_id })}</span>}
        {item.conversation_id && <span>{t('agent.memoryScope.conversation', { name: item.conversation_title || item.conversation_id })}</span>}
        {item.task_id && <span>{t('agent.memoryScope.task', { name: item.task_title || item.task_id })}</span>}
        {item.day_key && <span>{t('agent.memoryScope.day', { day: item.day_key, timezone: item.timezone || 'UTC' })}</span>}
      </div>
      <div className="agent-memory-actions"><Button onClick={() => { void sources(item) }}>{t('agent.memorySources')}{item.source_count !== undefined && ` (${new Intl.NumberFormat(locale).format(item.source_count)})`}</Button>
        {item.state !== 'active' && <><Button type="primary" disabled={!!busy} loading={busy === item.id} onClick={() => { void mutate(item, 'POST', '/confirm', { accepted: true }) }}>{t('agent.memoryConfirm')}</Button><Button disabled={!!busy} onClick={() => { void mutate(item, 'POST', '/confirm', { accepted: false }) }}>{t('agent.memoryReject')}</Button></>}
        {item.state === 'active' && <><Button disabled={!!busy} onClick={() => { void mutate(item, 'DELETE', '?forgetSources=false') }}>{t('agent.memoryDelete')}</Button><Button danger disabled={!!busy} onClick={() => modal.confirm({ title: t('agent.memoryForgetTitle'), content: t('agent.memoryForgetBody'), okText: t('agent.memoryForget'), cancelText: t('common.cancel'), onOk: () => mutate(item, 'DELETE', '?forgetSources=true') })}>{t('agent.memoryForget')}</Button></>}
      </div>
    </article>)}</div>
    {!loading && !failed && <div className="agent-memory-pagination"><span role="status">{t('agent.memoryTotal', { count: new Intl.NumberFormat(locale).format(total) })}</span><Button disabled={page === 0} onClick={() => setPage(value => value - 1)}>{t('agent.memoryPrevious')}</Button><Button disabled={(page + 1) * 20 >= total} onClick={() => setPage(value => value + 1)}>{t('agent.memoryNext')}</Button></div>}
    <Modal destroyOnClose open={evidence !== null} title={t('agent.memorySources')} footer={null} onCancel={() => { sourceRequest.current++; setEvidence(null); setSourceLoading(false) }}>
      {sourceLoading && <Spin size="small" />}<div className="agent-memory agent-memory-evidence">{evidence?.map((source) => <article className="agent-memory-card" key={source.sourceKey}>{source.available === false ? <p>{t('agent.memorySourceMissing')}</p> : <>{source.kind && <b>{t('agent.memorySource.' + source.kind)}</b>}{source.createdMs && <time className="agent-muted">{new Date(source.createdMs).toLocaleString(locale, { timeZone: timezone || 'UTC' })}</time>}<Markdown>{source.text || ''}</Markdown>{source.unchanged === false && <p className="agent-muted">{t('agent.memorySourceChanged')}</p>}{source.conversationId && <Button onClick={() => select(source.conversationId!, source.branchId, source.messageId)}>{t('agent.memoryOpenSource')}</Button>}</>}</article>)}</div>
    </Modal>
  </div>
}
