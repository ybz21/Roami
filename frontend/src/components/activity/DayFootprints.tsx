import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'

type DayData = {
  commits: { oid: string; at: number; repo: string; subject: string }[]
  usage: { at: number; dialogues: number; tasks: number }[]
  recordingFailed?: boolean
}

export default function DayFootprints({ date }: { date: Date }) {
  const { t, locale } = useI18n()
  const root = useRef<HTMLElement>(null)
  const from = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const end = new Date(from); end.setDate(end.getDate() + 1)
  const startAt = from.getTime() / 1000, endAt = end.getTime() / 1000
  const [data, setData] = useState<DayData | null>(null)
  const [error, setError] = useState(false)
  const [shown, setShown] = useState(12)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError(false); setShown(12)
    api('GET', `/activity/day?from=${startAt}&to=${endAt}`, undefined, { signal: controller.signal })
      .then((r) => { if (!controller.signal.aborted) setData(r.data) })
      .catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [startAt, endAt, retry])
  useEffect(() => {
    if (!data && !error) return
    const panel = root.current?.closest<HTMLElement>('.tt-sheet-body') || root.current?.closest<HTMLElement>('.tt-activity-panel')
    if (panel) panel.scrollTop = 0
  }, [data, error])
  const time = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' })
  const entries = [
    ...(data?.commits || []).map((commit) => ({ at: commit.at, key: commit.oid, title: commit.subject || t('activity.archivedCommit'), meta: `${commit.repo.split(/[\\/]/).filter(Boolean).pop() || t('activity.unknownProject')} · ${commit.oid.slice(0, 7)}` })),
    ...(data?.usage || []).flatMap((event, i) => [
      ...(event.dialogues ? [{ at: event.at, key: `dialogue-${i}`, title: t('activity.dialogueEvent', { count: event.dialogues }), meta: t('activity.usageEventScope') }] : []),
      ...(event.tasks ? [{ at: event.at, key: `task-${i}`, title: t('activity.taskEvent', { count: event.tasks }), meta: t('activity.usageEventScope') }] : []),
    ]),
  ].sort((a, b) => b.at - a.at || a.key.localeCompare(b.key))
  return <section ref={root} className="tt-activity-timeline" aria-label={t('activity.dayTimeline')}>
    <h4>{t('activity.dayTimeline')}</h4>
    {error ? <p role="alert">{t('activity.dayFailed')} <button type="button" className="tt-act" onClick={() => setRetry((n) => n + 1)}>{t('inbox.retry')}</button></p>
      : !data ? <p role="status">{t('common.loading')}</p>
        : entries.length === 0 ? <p>{t('activity.dayEmpty')}</p>
          : <ul>{entries.slice(0, shown).map((entry) => <li key={entry.key}><time dateTime={new Date(entry.at * 1000).toISOString()}>{time.format(new Date(entry.at * 1000))}</time><div><p>{entry.title}</p><span>{entry.meta}</span></div></li>)}</ul>}
    {entries.length > shown && <button type="button" className="tt-act" onClick={() => setShown((n) => n + 24)}>{t('activity.showMore', { count: entries.length - shown })}</button>}
    {data?.recordingFailed && <p role="alert">{t('activity.recordingFailed')}</p>}
  </section>
}
