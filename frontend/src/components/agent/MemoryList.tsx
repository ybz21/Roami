import { Fragment, type RefObject } from 'react'
import { Button, Skeleton } from 'antd'
import { ChevronRight, NotebookIcon } from '../../icons'
import { useBoundaryLoad } from './useBoundaryLoad'
import AgentPageBoundary from './AgentPageBoundary'
import { useI18n } from '../../i18n'
import { dailyMemory, type MemoryRecord } from './memory-record'

export default function MemoryList({ items, loading, failed, selected, date, scope, choose, clear, filtered, scroll, onScroll, activity = false, hasMore = false, loadMore, loadingMore = false, moreFailed = false }: {
  items: MemoryRecord[]; loading: boolean; failed: boolean; selected: string
  date: (timestamp: number | string) => string; scope: (record: MemoryRecord) => string
  choose: (id: string) => void; clear: () => void; filtered: boolean
  hasMore?: boolean; loadMore: () => void; loadingMore?: boolean; moreFailed?: boolean
  activity?: boolean; scroll: RefObject<HTMLDivElement>; onScroll: () => void
}) {
  const { t, locale } = useI18n()
  useBoundaryLoad(scroll, loadMore, hasMore && !loading && !loadingMore && !moreFailed)
  const number = (value: number) => Number.isFinite(value) ? new Intl.NumberFormat(locale).format(value) : t('agent.memoryCountUnknown')
  return <div className="memory-list-scroll" ref={scroll} onScroll={onScroll} aria-busy={loading}>
    {loading && !items.length ? <div className="memory-loading"><Skeleton active /><Skeleton active /></div> : items.map((item, index) => {
      const daily = dailyMemory(item)
      return <Fragment key={item.id}>
        {item.day_key && item.day_key !== items[index - 1]?.day_key && <h3 className="memory-day">{date(item.day_key + 'T12:00:00')}</h3>}
        <button type="button" className="memory-row" aria-current={item.id === selected ? 'true' : undefined} onClick={() => choose(item.id)}>
          <span className="memory-row-head"><strong>{item.day_key ? scope(item) : item.title}</strong>{item.state === 'conflict' ? <span className="memory-warning">{t('agent.memoryBrowse.conflict')}</span> : <ChevronRight size={16} />}</span>
          <span className="memory-row-summary">{daily ? t('agent.memoryBrowse.activitySummary', { turns: number(daily.counts.userTurns), completed: number(daily.counts.tasksCompleted) }) : item.body}</span>
          {!item.day_key && <span className="memory-row-meta"><span>{scope(item)}</span>{item.updated_ms && <time dateTime={new Date(item.updated_ms).toISOString()}>{date(item.updated_ms)}</time>}</span>}
        </button>
      </Fragment>
    })}
    {!items.length && !loading && !failed && <div className="memory-empty" role="status"><NotebookIcon size={24} /><p>{t(filtered ? 'agent.memoryBrowse.noResults' : activity ? 'agent.memoryNoActivity' : 'agent.noMemories')}</p>{filtered && <Button onClick={clear}>{t('agent.memoryBrowse.clear')}</Button>}</div>}
    <AgentPageBoundary more={hasMore} loading={loadingMore} failed={moreFailed} load={loadMore} />
  </div>
}
