import { useEffect, useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'

type DaySummary = {
  projects: { repo: string; count: number }[]
  dialogues: number
  tasks: number
  commits: number
  recordingFailed?: boolean
}

export default function DayFootprints({ date, revision }: { date: Date; revision: number }) {
  const { t, locale } = useI18n()
  const from = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const end = new Date(from); end.setDate(end.getDate() + 1)
  const startAt = from.getTime() / 1000, endAt = end.getTime() / 1000
  const [data, setData] = useState<DaySummary | null>(null)
  const [error, setError] = useState(false)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError(false)
    api('GET', `/activity/day?from=${startAt}&to=${endAt}`, undefined, { signal: controller.signal })
      .then((r) => { if (!controller.signal.aborted) setData(r.data) })
      .catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [startAt, endAt, revision, retry])
  const number = (n: number) => new Intl.NumberFormat(locale).format(n)
  return <section className="tt-activity-day-panel" aria-label={t('activity.dayTimeline')}>
    <h4>{new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'short', day: 'numeric', weekday: 'short' }).format(from)}</h4>
    {error ? <p role="alert" className="tt-data-error">{t('activity.dayFailed')} <button type="button" className="tt-act" onClick={() => setRetry((n) => n + 1)}>{t('inbox.retry')}</button></p>
      : !data ? <p role="status">{t('common.loading')}</p>
        : <>
          <p>{t('activity.usageSummary', { dialogues: number(data.dialogues), tasks: number(data.tasks), commits: number(data.commits) })}</p>
          <ul className="tt-activity-project-counts">{data.projects.map((project) => <li key={project.repo}><span>{project.repo.split(/[\\/]/).filter(Boolean).pop() || t('activity.unknownProject')}</span><b>{t('activity.projectCommits', { count: number(project.count) })}</b></li>)}</ul>
          {!data.dialogues && !data.tasks && !data.commits && <p>{t('activity.dayEmpty')}</p>}
        </>}
    {data?.recordingFailed && <p role="alert" className="tt-data-error">{t('activity.recordingFailed')}</p>}
  </section>
}
