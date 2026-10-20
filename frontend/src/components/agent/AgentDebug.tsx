import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Segmented, Select, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { DownloadIcon } from '../files/file-icons'
import { useAgentData } from './useAgentData'
import { openAgentPage } from './agent-page-route'
import { useAgentOutboxDebug } from './agent-outbox-debug'
import './agent-debug.css'

type QueueItem = { id: string; state: string; createdMs: number; finishedMs?: number | null; preview?: string; executor?: string; jobState?: string; availableMs?: number; deferred?: number }
type Page = { items: QueueItem[]; total: number; nextOffset: number | null; activeTotal?: number }
type Context = Record<string, string | number | null>
type Snapshot = { branchId: string; observedMs: number; windowMinutes: number; active: boolean; requests: Page; queue: { turns: Page; tasks: Page; compactions: { id: string; state: string }[] }; context?: Context; scheduler: { mainSlots: number; workerSlots: number }; limits: Context }
type Span = { spanId: string; parentSpanId: string | null; name: string; state: string; startedMs: number; durationMs: number | null; attributes: Record<string, any> }
type Trace = { traceId: string; observedAtMs: number; spans: Span[]; summary: { active: boolean; durationMs: number; firstCommittedTextMs: number | null; modelCalls: number; toolCalls: number; taskStates: Record<string, string> }; coverage: { externalAgentInternals: boolean }; truncated?: boolean }

export default function AgentDebug({ cid, branch, node, selected, onSelect }: { cid: string; branch: string; node: string | null; selected: string; onSelect: (id: string) => void }) {
  const { t, locale } = useI18n()
  const [tab, setTab] = useState('trace'), [minutes, setMinutes] = useState(60)
  const [offset, setOffset] = useState(0), [queueOffset, setQueueOffset] = useState(0), [taskOffset, setTaskOffset] = useState(0)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set()), [shownSpans, setShownSpans] = useState(200)
  const [active, setActive] = useState(false), [traceActive, setTraceActive] = useState(false), [exporting, setExporting] = useState(false), [exportFailed, setExportFailed] = useState(false)
  const scope = `${node || 'local'}:${cid}:${branch}`
  const currentScope = useRef(scope); currentScope.current = scope
  const base = `/agent/conversations/${encodeURIComponent(cid)}/debug`
  const query = new URLSearchParams({ minutes: String(minutes), offset: String(offset), queueOffset: String(queueOffset), taskOffset: String(taskOffset), limit: '30', includeContext: String(tab === 'context') })
  if (branch) query.set('branch', branch)
  const snapshot = useAgentData<Snapshot>(cid ? base + '?' + query : null, 0, active ? 2000 : 0)
  const target = /^(turn|task):(.+)$/.exec(selected)
  const traceQuery = new URLSearchParams()
  if (branch) traceQuery.set('branch', branch)
  if (target) traceQuery.set(target[1] === 'turn' ? 'turnId' : 'taskId', target[2])
  const tracePath = target && cid ? base + '/trace?' + traceQuery : null
  const trace = useAgentData<Trace>(tracePath, 0, traceActive ? 2000 : 0)
  const local = useAgentOutboxDebug(`roami.agent.draft.${node || 'local'}.${cid || 'new'}`)
  useEffect(() => { if (snapshot.value) setActive(snapshot.value.active) }, [snapshot.value])
  useEffect(() => { setTraceActive(!!trace.value?.summary.active) }, [trace.value])
  useEffect(() => { setExpanded(new Set()); setShownSpans(200) }, [trace.value?.traceId])
  useEffect(() => { currentScope.current = scope; return () => { currentScope.current = '' } }, [scope])
  const formatter = useMemo(() => new Intl.NumberFormat(locale), [locale])
  const number = (value: number) => formatter.format(value)
  const duration = (value: number | null | undefined) => value == null ? t('agent.debug.unknown') : t('agent.debug.milliseconds', { value: number(Math.round(value)) })
  const state = (value: string) => value === 'settled' ? t('agent.activity.finished') : value === 'completed' ? t('agent.state.succeeded') : ['succeeded', 'queued', 'preparing', 'running', 'verifying', 'waiting_user', 'cancelling', 'failed', 'cancelled', 'interrupted', 'unknown', 'accepted', 'starting', 'stopping'].includes(value) ? t('agent.state.' + value) : ['sending', 'unconfirmed'].includes(value) ? t('agent.outbox.' + value) : value === 'waiting' ? t('agent.state.queued') : value
  const value = (item: string | number | null) => item == null || item === '' ? t('agent.debug.unknown') : typeof item === 'number' ? number(item) : item
  const contextTable = (data: Context | undefined, limits = false) => data ? <dl className="agent-debug-values">{Object.entries(data).map(([key, item]) => <div key={key}><dt>{key}</dt><dd>{limits && (item === 0 || item == null) ? t('agent.debug.unlimited') : value(item)}</dd></div>)}</dl> : <p className="agent-debug-muted">{t('agent.debug.unknown')}</p>
  const pageControls = (page: Page, current: number, change: (next: number) => void) => page.total > 30 && <div className="agent-debug-pagination"><Button disabled={!current} onClick={() => change(Math.max(0, current - 30))}>{t('agent.debug.previous')}</Button><span>{t('agent.debug.page', { from: Math.min(current + 1, page.total), to: Math.min(current + 30, page.total), total: page.total })}</span><Button disabled={page.nextOffset == null} onClick={() => page.nextOffset != null && change(page.nextOffset)}>{t('agent.debug.next')}</Button></div>
  const selectRow = (item: QueueItem, kind: 'turn' | 'task', history = false) => <button type="button" className="agent-debug-row" key={item.id} onClick={() => { setTab('trace'); onSelect(kind + ':' + item.id) }}><span><strong>{item.preview || item.id}</strong><small>{item.executor || item.jobState || item.id}</small></span><span>{state(item.state)}{snapshot.value && <small>{duration(history && item.finishedMs != null ? Math.max(0, item.finishedMs - item.createdMs) : Math.max(0, snapshot.value.observedMs - item.createdMs))}</small>}</span></button>
  const exportTrace = async () => {
    if (!tracePath || exporting) return
    const owner = scope
    setExporting(true); setExportFailed(false)
    try {
      const { data } = await api('GET', tracePath + '&format=chrome')
      if (currentScope.current !== owner) return
      const url = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: 'application/json' }))
      const link = document.createElement('a'); link.href = url; link.download = `roami-trace-${trace.value?.traceId || 'export'}.json`; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch { if (currentScope.current === owner) setExportFailed(true) }
    finally { if (currentScope.current === owner) setExporting(false) }
  }
  const children = useMemo(() => {
    const result = new Map<string | null, Span[]>()
    for (const span of trace.value?.spans || []) { const group = result.get(span.parentSpanId) || []; group.push(span); result.set(span.parentSpanId, group) }
    return result
  }, [trace.value])
  const ordered = useMemo(() => {
    const result: { item: Span; depth: number }[] = [], visited = new Set<string>()
    const stack = (children.get(null) || []).map(item => ({ item, depth: 0 })).reverse()
    while (stack.length) {
      const entry = stack.pop()!
      if (visited.has(entry.item.spanId)) continue
      visited.add(entry.item.spanId); result.push(entry)
      for (const item of [...(children.get(entry.item.spanId) || [])].reverse()) stack.push({ item, depth: entry.depth + 1 })
    }
    return result
  }, [children])
  const spanDetails = (item: Span) => <div className="agent-debug-span-detail"><code>{item.spanId}</code>{item.attributes.taskId && <Button onClick={() => openAgentPage('tasks', item.attributes.taskId)}>{t('agent.tasks')}</Button>}<p>{t(item.attributes.timingSource === 'measured' ? 'agent.debug.measured' : 'agent.debug.inferred')}</p>{item.name === 'model.request' && contextTable(item.attributes.context)}{item.attributes.limits && contextTable(item.attributes.limits, true)}<dl className="agent-debug-values">{Object.entries(item.attributes).filter(([key, entry]) => !['context', 'limits'].includes(key) && (entry == null || ['string', 'number', 'boolean'].includes(typeof entry))).map(([key, entry]) => <div key={key}><dt>{key}</dt><dd>{typeof entry === 'boolean' ? String(entry) : value(entry)}</dd></div>)}</dl></div>
  const spans = ordered.slice(0, shownSpans).map(({ item, depth }) => <li key={item.spanId} style={{ paddingInlineStart: `calc(var(--sp-2) * ${Math.min(depth, 6)})` }}><details open={expanded.has(item.spanId)} onToggle={event => { const open = event.currentTarget.open; setExpanded(previous => { const next = new Set(previous); if (open) next.add(item.spanId); else next.delete(item.spanId); return next }) }}><summary><span>{item.name}</span><span>{state(item.state)} · {duration(item.durationMs == null && item.state === 'running' ? Math.max(0, trace.value!.observedAtMs - item.startedMs) : item.durationMs)}</span></summary>{expanded.has(item.spanId) && spanDetails(item)}</details></li>)
  return <div className="agent-debug">
    <Segmented block value={tab} onChange={next => setTab(String(next))} options={[{ value: 'trace', label: t('agent.debug.trace') }, { value: 'queue', label: t('agent.debug.queue') }, { value: 'context', label: t('agent.context') }]} />
    <details className="agent-debug-guide"><summary>{t('agent.debug.how')}</summary><p>{t('agent.debug.guideTrace')}</p><p>{t('agent.debug.guideQueue')}</p><p>{t('agent.debug.guideContext')}</p></details>
    {(snapshot.failed || trace.failed || exportFailed) && <p role="alert">{t([snapshot.errorCode, trace.errorCode].some(code => code === 'TRACE_LINK_LIMIT' || code === 'TRACE_SPAN_LIMIT') ? 'agent.debug.queryLimit' : 'agent.requestFailed')}</p>}
    {snapshot.loading && <Spin />}
    {tab === 'trace' && <>
      {!selected && <><div className="agent-debug-toolbar"><Select aria-label={t('agent.debug.window')} value={minutes} options={[15, 60, 1440].map(item => ({ value: item, label: t('agent.debug.window' + item) }))} onChange={next => { setMinutes(next); setOffset(0) }} /></div>{snapshot.value && <>{snapshot.value.requests.items.length ? <div>{snapshot.value.requests.items.map(item => selectRow(item, 'turn', true))}</div> : <p className="agent-debug-muted">{t('agent.debug.empty')}</p>}{pageControls(snapshot.value.requests, offset, setOffset)}</>}</>}
      {selected && <>{trace.loading && <Spin />}{trace.value && <><div className="agent-debug-toolbar"><code>{trace.value.traceId}</code><Button icon={<DownloadIcon />} loading={exporting} onClick={() => void exportTrace()}>{t('agent.debug.export')}</Button></div><dl className="agent-debug-values"><div><dt>{t('agent.debug.elapsed')}</dt><dd>{duration(trace.value.summary.durationMs)}</dd></div><div><dt>{t('agent.debug.firstText')}</dt><dd>{duration(trace.value.summary.firstCommittedTextMs)}</dd></div><div><dt>{t('agent.debug.calls')}</dt><dd>{t('agent.debug.callCounts', { models: trace.value.summary.modelCalls, tools: trace.value.summary.toolCalls, tasks: Object.keys(trace.value.summary.taskStates).length })}</dd></div></dl><p className="agent-debug-muted">{t('agent.debug.opaque')}</p>{trace.value.truncated && <p role="status">{t('agent.debug.truncated')}</p>}<ul className="agent-debug-spans">{spans}</ul>{ordered.length > shownSpans && <Button onClick={() => setShownSpans(current => current + 200)}>{t('agent.debug.moreSpans')}</Button>}</>}</>}
    </>}
    {tab === 'queue' && <>
      <h3>{t('agent.debug.localQueue')}{local.paused && <small>{t('agent.outbox.paused')}</small>}</h3>
      {local.items.length ? local.items.map(item => <div className="agent-debug-row" key={item.id}><code>{item.id}</code><span>{state(item.state)}<small>{t('agent.debug.attachments', { count: item.attachments })}</small></span></div>) : <p className="agent-debug-muted">{t('agent.debug.emptyQueue')}</p>}
      {snapshot.value && <><h3>{t('agent.debug.mainQueue')}</h3>{snapshot.value.queue.turns.items.length ? snapshot.value.queue.turns.items.map(item => selectRow(item, 'turn')) : <p className="agent-debug-muted">{t('agent.debug.emptyQueue')}</p>}{pageControls(snapshot.value.queue.turns, queueOffset, setQueueOffset)}<h3>{t('agent.tasks')}</h3>{snapshot.value.queue.tasks.items.length ? snapshot.value.queue.tasks.items.map(item => selectRow(item, 'task')) : <p className="agent-debug-muted">{t('agent.debug.emptyQueue')}</p>}{pageControls(snapshot.value.queue.tasks, taskOffset, setTaskOffset)}{!!snapshot.value.queue.compactions.length && <><h3>{t('agent.debug.compaction')}</h3>{snapshot.value.queue.compactions.map(item => <div className="agent-debug-row" key={item.id}><code>{item.id}</code><span>{state(item.state)}</span></div>)}</>}<p className="agent-debug-muted">{t('agent.debug.slots', { main: snapshot.value.scheduler.mainSlots, workers: snapshot.value.scheduler.workerSlots })}</p></>}
    </>}
    {tab === 'context' && <><p className="agent-debug-muted">{t('agent.debug.currentContext')}</p>{contextTable(snapshot.value?.context)}{snapshot.value && <><h3>{t('agent.debug.limits')}</h3><dl className="agent-debug-values">{Object.entries(snapshot.value.limits).map(([key, item]) => <div key={key}><dt>{key}</dt><dd>{item === 0 ? t('agent.debug.unlimited') : value(item)}</dd></div>)}</dl></>}</>}
  </div>
}
