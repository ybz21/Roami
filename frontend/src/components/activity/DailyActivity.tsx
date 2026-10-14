import { useCallback, useEffect, useRef, useState } from 'react'
import { Modal } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { ChevronLeft, ChevronRight, CloseIcon } from '../../icons'
import { MobileSheet } from '../shell/MobileSheet'
import { activityCalendar, activityLevel, dayKey, type ActivityDay, type ActivityEvent } from './activity-calendar'
import DayFootprints from './DayFootprints'
import './daily-activity.css'

type Activity = { commits: { oid: string; at: number }[]; usage?: ActivityEvent[]; commitHistoryFailed?: boolean; recordingFailed?: boolean; repositories: number; failed: number }
export default function DailyActivity() {
  const { t, locale } = useI18n()
  const { phone, coarse } = useLayout()
  const [data, setData] = useState<Activity | null>(null)
  const [error, setError] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const [selected, setSelected] = useState(() => dayKey(new Date()))
  const [now, setNow] = useState(() => new Date())
  const scroll = useRef<HTMLDivElement>(null)
  const load = useCallback(async (signal: AbortSignal) => {
    try {
      const response = await api('GET', '/activity/daily', undefined, { signal })
      if (!signal.aborted) { setData(response.data); setError(false); setNow(new Date()) }
    } catch { if (!signal.aborted) setError(true) }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    const update = () => void load(controller.signal)
    update()
    const timer = setInterval(update, 60000)
    window.addEventListener('roam:footprints-updated', update)
    return () => { controller.abort(); clearInterval(timer); window.removeEventListener('roam:footprints-updated', update) }
  }, [load, refresh])
  useEffect(() => { if (scroll.current) scroll.current.scrollLeft = scroll.current.scrollWidth }, [Boolean(data), coarse, phone, expanded])
  const calendar = activityCalendar([...(data?.usage || []), ...(data?.commits || []).map((c) => ({ at: c.at, commits: 1 }))], now)
  const numberFormat = new Intl.NumberFormat(locale)
  const number = (n: number) => numberFormat.format(n)
  const dateFormat = new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'short', day: 'numeric', weekday: 'short' })
  const dateText = (date: Date) => dateFormat.format(date)
  const detail = calendar.days.find((day) => day.key === selected) || calendar.days[calendar.days.length - 1]
  const dayLabel = (day: ActivityDay) => t('activity.dayUsage', { date: dateText(day.date), dialogues: number(day.dialogues), tasks: number(day.tasks), commits: number(day.commits) })
  const stats = <div className="tt-activity-stats">
    {([[calendar.totals.dialogues, 'activity.dialogues'], [calendar.totals.tasks, 'activity.tasks'], [calendar.totals.commits, 'activity.commits'], [calendar.active, 'activity.active'], [calendar.current, 'activity.streak'], [calendar.longest, 'activity.longest']] as const).map(([value, key]) => <div key={key}><b>{number(value)}</b><span>{t(key)}</span></div>)}
  </div>
  const heatmap = (weeks: (ActivityDay | null)[][], interactive: boolean, fit = false) => <span className={`tt-activity-weeks${fit ? ' tt-activity-fit' : ''}`} style={fit ? { gridTemplateColumns: `repeat(${weeks.length}, minmax(var(--sp-2), 1fr))` } : undefined} aria-hidden={interactive ? undefined : true}>
    {weeks.map((week, i) => {
      const first = week.find((day) => day && (day.date.getDate() === 1 || i === 0))
      return <span className="tt-activity-week" key={i}>
        <span className="tt-activity-month">{first ? new Intl.DateTimeFormat(locale, { month: 'short' }).format(first.date) : ''}</span>
        {week.map((day, row) => !day ? <span className="tt-activity-blank" key={row} /> : interactive ? <button type="button" key={day.key} className={`tt-activity-day level-${activityLevel(day.count, calendar.thresholds)}`} aria-label={dayLabel(day)} data-day={day.key} tabIndex={detail.key === day.key ? 0 : -1} aria-pressed={detail.key === day.key} title={dayLabel(day)} onClick={(event) => {
          setSelected(day.key); setExpanded(true)
          const panel = event.currentTarget.closest<HTMLElement>('.tt-sheet-body') || event.currentTarget.closest<HTMLElement>('.tt-activity-panel')
          panel?.scrollTo?.({ top: 0, behavior: 'smooth' })
        }} onKeyDown={(event) => {
          const offset = { ArrowRight: 7, ArrowLeft: -7, ArrowDown: 1, ArrowUp: -1 }[event.key]
          if (offset === undefined && event.key !== 'Home' && event.key !== 'End') return
          event.preventDefault()
          const index = calendar.days.findIndex((item) => item.key === day.key)
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? calendar.days.length - 1 : Math.max(0, Math.min(calendar.days.length - 1, index + offset!))
          const key = calendar.days[next].key
          setSelected(key)
          event.currentTarget.closest('.tt-activity-weeks')?.querySelector<HTMLButtonElement>(`[data-day="${key}"]`)?.focus()
        }}><i /></button> : <span className={`tt-activity-day tt-activity-static-day level-${activityLevel(day.count, calendar.thresholds)}`} key={day.key}><i /></span>)}
      </span>
    })}
  </span>
  const legend = <div className="tt-activity-footer"><span>{t('activity.less')}</span><div className="tt-activity-legend" aria-hidden="true">{[0, 1, 2, 3, 4].map((level) => <i className={`level-${level}`} key={level} />)}</div><span>{t('activity.more')}</span></div>
  const scope = <p className="tt-activity-scope">{t('activity.usageScope')}{' '}{t('activity.colorScope')}{' '}{t('activity.scope', { count: number(data?.repositories || 0) })}{!!data?.failed && <span role="status"> {t('activity.partial', { count: number(data.failed) })}</span>}</p>
  const detailIndex = calendar.days.findIndex((day) => day.key === detail.key)
  const details = <div className="tt-activity-panel">
    <div className="tt-activity-date-nav">
      <button type="button" disabled={detailIndex === 0} aria-label={t('activity.previousDay')} onClick={() => setSelected(calendar.days[detailIndex - 1].key)}><ChevronLeft /></button>
      <label><span>{t('activity.chooseDate')}</span><input type="date" value={detail.key} min={calendar.days[0].key} max={calendar.days[calendar.days.length - 1].key} onChange={(event) => { if (calendar.days.some((day) => day.key === event.target.value)) setSelected(event.target.value) }} /></label>
      <button type="button" disabled={detailIndex === calendar.days.length - 1} aria-label={t('activity.nextDay')} onClick={() => setSelected(calendar.days[detailIndex + 1].key)}><ChevronRight /></button>
    </div>
    <p className="tt-activity-detail" aria-live="polite">{dayLabel(detail)}</p>
    <p className="tt-activity-scope">{t('activity.dayCommits', { count: number(detail.commits) })}</p>
    <DayFootprints date={detail.date} />
    <p className="tt-activity-scope">{t('activity.year')}</p>
    {stats}
    <div className="tt-activity-scroll" ref={scroll}>{heatmap(calendar.weeks, true)}</div>
    {legend}
    {calendar.total === 0 && <p>{t('activity.empty')}</p>}
    {scope}
  </div>
  return <section className={`tt-activity${phone ? ' tt-activity-compact' : ' tt-activity-desktop'}`} aria-label={t('activity.title')}>
    <div className="tt-activity-overview">
      <div className="tt-activity-copy">
        <div className="tt-activity-heading"><h3>{t('activity.title')}</h3><span>{phone ? t('activity.streakSummary', { count: number(calendar.current) }) : t('activity.year')}</span></div>
        {error && <div role="alert" className="tt-data-error">{t('activity.failed')} <button type="button" className="tt-act" onClick={() => setRefresh((value) => value + 1)}>{t('inbox.retry')}</button></div>}
        {data?.commitHistoryFailed && <p role="alert" className="tt-data-error">{t('activity.commitHistoryFailed')}</p>}
        {data?.recordingFailed && <p role="alert" className="tt-data-error">{t('activity.recordingFailed')}</p>}
        {!data ? <p role="status">{t(error ? 'activity.unavailable' : 'common.loading')}</p> : <p className="tt-activity-summary">{t('activity.usageSummary', { dialogues: number(calendar.totals.dialogues), tasks: number(calendar.totals.tasks), commits: number(calendar.totals.commits) })}</p>}
      </div>
      {data && phone && <button type="button" className="tt-activity-preview" aria-label={t('activity.viewDetails')} onClick={() => setExpanded(true)}>
        {heatmap(calendar.weeks.slice(-16), false)}
        <span className="tt-activity-preview-caption"><span>{t('activity.recentWeeks')}</span><span>{t('activity.viewYear')}<ChevronRight size={14} /></span></span>
      </button>}
    </div>
    {data && !phone && <>
      <div className="tt-activity-year">
        <div className="tt-activity-weekdays" aria-hidden="true"><span className="tt-activity-month" />{Array.from({ length: 7 }, (_, row) => <span key={row}>{[1, 3, 5].includes(row) ? new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(new Date(2023, 0, 1 + row)) : ''}</span>)}</div>
        <div className="tt-activity-scroll tt-activity-year-scroll">{heatmap(calendar.weeks, !coarse, true)}</div>
      </div>
      <div className="tt-activity-year-footer">
        <button type="button" className="tt-act" aria-label={t('activity.viewDetails')} onClick={() => setExpanded(true)}>{t('activity.countingDetails')}</button>
        <span className="tt-activity-day-summary" aria-live="polite">{dayLabel(detail)}</span>
        {legend}
      </div>
    </>}
    {phone ? <MobileSheet open={expanded} title={t('activity.title')} onClose={() => setExpanded(false)}>{details}</MobileSheet>
      : <Modal open={expanded} title={t('activity.title')} onCancel={() => setExpanded(false)} footer={null} width="80%" style={{ maxWidth: 'calc(var(--sp-5) * 48)' }} className="tt-activity-modal" closeIcon={<CloseIcon />} destroyOnHidden afterOpenChange={(open) => { if (open && scroll.current) scroll.current.scrollLeft = scroll.current.scrollWidth }}>{details}</Modal>}
  </section>
}
