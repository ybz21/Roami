import { type ReactNode, useEffect, useRef, useState } from 'react'
import { Button, Skeleton, Spin } from 'antd'
import { CheckIcon, ChevronLeft, ChevronRight, ClockIcon, NotebookIcon, OpenInIcon } from '../../icons'
import { useI18n } from '../../i18n'
import Markdown from '../markdown/Markdown'
import { useAgentData } from './useAgentData'
import { dailyMemory, memoryScope, type MemoryDetail as Detail, type MemoryRecord } from './memory-record'

export default function MemoryDetail({ id, record, data, loading, failed, missing, retry, scope, date, select, panel, back, more, busy, confirm, reject, revision }: {
  id: string; record?: MemoryRecord; data?: Detail; loading: boolean; failed: boolean; missing: boolean; retry: () => void
  scope: (item: MemoryRecord) => string; date: (value: number | string, full?: boolean) => string
  select: (cid: string, branch?: string, message?: string) => void; panel: boolean; back: () => void; more?: ReactNode
  busy: boolean; confirm: () => Promise<unknown>; reject: () => Promise<unknown>; revision: number
}) {
  const { t, locale } = useI18n(), [historyId, setHistoryId] = useState('')
  const historyOpen = !!id && historyId === id
  const history = useAgentData<{ items: MemoryRecord[]; truncated: boolean }>(historyOpen && id ? '/agent/memories/' + encodeURIComponent(id) + '/history' : null, 15_000)
  const historyRefresh = useRef(history.refresh); historyRefresh.current = history.refresh
  useEffect(() => { if (historyOpen) historyRefresh.current() }, [revision])
  const daily = record && dailyMemory(record), comparing = data?.current && data.current.body !== record?.body
  if (!id) return <div className="memory-empty"><NotebookIcon size={28} /><p>{t('agent.memoryBrowse.choose')}</p></div>
  const bar = <div className="memory-detailbar">{panel && <button type="button" className="tt-act" onClick={back}><ChevronLeft size={18} />{t('common.back')}</button>}<span>{t(daily ? 'agent.memoryBrowse.activityDetail' : 'agent.memoryBrowse.detail')}</span>{more}</div>
  if (missing) return <>{bar}<div className="memory-empty" role="alert"><p>{t('agent.memoryBrowse.unavailable')}</p><Button onClick={back}>{t('common.back')}</Button></div></>
  if (!record) return <>{bar}<div className="memory-loading">{failed ? <p role="alert">{t('agent.requestFailed')} <Button onClick={retry}>{t('agent.retry')}</Button></p> : <Skeleton active />}</div></>
  return <>{bar}<div className="memory-detail-scroll" key={id}><article className="memory-reading">
    <div className="memory-kicker"><span>{t(record.day_key ? 'agent.memoryView.activity' : 'agent.memoryKind.' + (record.kind || 'fact'))}</span><span className={record.state !== 'active' ? 'memory-warning' : ''}>{t(record.state === 'active' ? 'agent.memoryBrowse.saved' : record.state === 'conflict' ? 'agent.memoryBrowse.conflict' : 'agent.memoryBrowse.review')}</span></div>
    <h2>{daily ? scope(record) : record.title}</h2>
    {daily ? <><p className="memory-muted">{date(record.day_key + 'T12:00:00')} · {record.timezone || 'UTC'}</p><dl className="memory-activity-grid">{['userTurns', 'tasksCreated', 'tasksCompleted', 'tasksFailed', 'tasksCancelled', 'tasksInterrupted'].map(key => <div key={key}><dt>{t('agent.count.' + key)}</dt><dd>{Number.isFinite(daily.counts[key]) ? new Intl.NumberFormat(locale).format(daily.counts[key]) : t('agent.memoryCountUnknown')}</dd></div>)}</dl></> : comparing ? <div className="memory-comparison"><section><h3>{t('agent.memoryBrowse.current')}</h3><Markdown>{data.current.body}</Markdown></section><section><h3>{t('agent.memoryBrowse.proposed')}</h3><Markdown>{record.body}</Markdown></section></div> : <div className="memory-full-body"><Markdown>{record.body}</Markdown></div>}
    {record.state !== 'active' && <p className="memory-muted">{t('agent.memoryBrowse.reviewHint')}</p>}
    {!daily && <section className="memory-detail-section"><h3>{t('agent.memoryBrowse.scope')}</h3><strong>{scope(record)}</strong><p className="memory-muted">{t('agent.memoryBrowse.' + memoryScope(record) + 'Hint')}</p></section>}
    <section className="memory-detail-section"><h3>{t('agent.memoryBrowse.source')}</h3>
      {loading && <Spin size="small" />}{failed && <p role="alert">{t('agent.memoryBrowse.sourceFailed')} <Button onClick={retry}>{t('agent.retry')}</Button></p>}
      {data && !data.evidence.length && <p className="memory-muted">{t('agent.memorySourceMissing')}</p>}
      {data?.evidence.map(source => <div className="memory-source" key={source.sourceKey}>{source.available === false ? <p className="memory-muted">{t('agent.memorySourceMissing')}</p> : <>
        <div className="memory-source-heading"><NotebookIcon size={18} /><strong>{source.conversationTitle || t('agent.memoryBrowse.source')}</strong></div>
        {source.createdMs && <time className="memory-muted" dateTime={new Date(source.createdMs).toISOString()}>{date(source.createdMs, true)}</time>}
        <blockquote>{source.text || t('agent.memoryBrowse.noQuote')}</blockquote>
        {source.unchanged === false && <p className="memory-warning">{t('agent.memoryBrowse.sourceChanged')}</p>}
        {source.truncated && <p className="memory-muted">{t('agent.memoryBrowse.sourceTruncated')}</p>}
        {source.conversationId && <button type="button" className="tt-act" onClick={() => select(source.conversationId, source.branchId, source.messageId)}>{t('agent.memoryOpenSource')}<OpenInIcon size={16} /></button>}
      </>}</div>)}
    </section>
    {!daily && <section className="memory-detail-section memory-changes"><button type="button" className="memory-history-toggle" aria-expanded={historyOpen} onClick={() => setHistoryId(value => value === id ? '' : id)}>{t('agent.memoryBrowse.history')}<ChevronRight size={16} /></button>{historyOpen && <div>
      <div className="memory-history-entry"><ClockIcon size={16} /><div><strong>{t(record.state === 'active' ? 'agent.memoryBrowse.saved' : 'agent.memoryBrowse.review')}</strong>{record.updated_ms && <p>{date(record.updated_ms, true)}</p>}</div></div>
      {history.loading && <Spin size="small" />}{history.failed && <p role="alert">{t('agent.requestFailed')} <Button onClick={history.refresh}>{t('agent.retry')}</Button></p>}
      {history.value?.items.map(item => <div className="memory-history-entry" key={item.id}>{item.relation === 'merged' ? <CheckIcon size={16} /> : <ClockIcon size={16} />}<div><strong>{t(item.relation === 'merged' ? 'agent.memoryBrowse.merged' : 'agent.memoryBrowse.previous')}</strong>{item.updated_ms && <p>{date(item.updated_ms, true)}</p>}<Markdown>{item.body}</Markdown></div></div>)}
      {history.value?.truncated && <p className="memory-muted">{t('agent.memoryBrowse.historyTruncated')}</p>}
    </div>}</section>}
  </article></div>{record.state !== 'active' && <footer className="memory-detail-actions"><Button disabled={busy} onClick={() => { void reject() }}>{t('agent.memoryReject')}</Button><Button type="primary" disabled={busy || loading || failed || !data?.canConfirm} onClick={() => { void confirm() }}>{t(comparing ? 'agent.memoryBrowse.replace' : 'agent.memoryConfirm')}</Button></footer>}</>
}
