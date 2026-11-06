import { useEffect, useRef, useState } from 'react'
import { Button, Spin } from 'antd'
import { api } from '../../../api'
import { useI18n } from '../../../i18n'
import { metricConnector, type Workspace } from './okr-workspace'

export default function OkrReviewEvidence({ projectId, reviewId }: { projectId: string; reviewId: string }) {
  const { t, locale } = useI18n()
  const [snapshot, setSnapshot] = useState<Workspace | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const attempted = useRef(false)
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  const load = async () => {
    if (request.current || snapshot) return
    const controller = new AbortController()
    request.current = controller
    setLoading(true); setFailed(false)
    try {
      const response = await api('GET', '/projects/' + encodeURIComponent(projectId) + '/okr/reviews/' + encodeURIComponent(reviewId) + '/evidence', undefined, { signal: controller.signal })
      if (!controller.signal.aborted) {
        if (response.data) setSnapshot(response.data)
        else setFailed(true)
      }
    } catch { if (!controller.signal.aborted) setFailed(true) }
    finally { if (!controller.signal.aborted) { request.current = null; setLoading(false) } }
  }
  const number = (value: number) => new Intl.NumberFormat(locale, { maximumSignificantDigits: 21 }).format(value)
  const date = (value: string) => new Intl.DateTimeFormat(locale, { timeZone: 'Asia/Shanghai', dateStyle: 'medium', ...(value.length > 10 ? { timeStyle: 'medium' as const } : {}) }).format(new Date(value.length === 10 ? value + 'T00:00:00+08:00' : value))
  return <details className="okr-review-evidence" onToggle={event => { if (event.currentTarget.open && !attempted.current) { attempted.current = true; void load() } }}>
    <summary>{t('okr.viewEvidence')}</summary>
    {loading && <Spin />}
    {failed && <p role="alert">{t('okr.evidenceFailed')} <Button onClick={() => void load()}>{t('inbox.retry')}</Button></p>}
    {snapshot && <div>
      <p className="okr-muted">{t('okr.snapshotRevision', { revision: number(snapshot.revision) })}</p>
      <h4>{snapshot.objective}</h4>
      <p>{t('okr.period', { start: date(snapshot.startDate), end: date(snapshot.endDate) })}</p>
      <h4>{t('okr.keyResults')}</h4>
      {snapshot.keyResults.map(kr => <p key={kr.id}>{t('okr.snapshotKr', { title: kr.title, metric: snapshot.metrics.find(m => m.id === kr.metricId)?.name || '', mode: t('okr.mode.' + kr.mode), target: number(kr.target), date: date(kr.dueDate) })}</p>)}
      <h4>{t('okr.metrics')}</h4>
      {snapshot.metrics.map(metric => <div className="okr-version" key={metric.id}><strong>{metric.name}</strong><span>{metric.unit}</span><span>{metricConnector(snapshot, metric.id)?.name || (metric.source === 'github' ? t('okr.githubSource', { repo: metric.repo, field: t('okr.github.' + metric.field) }) : t('okr.source.manual'))}</span>{metric.sourceKey && <code>{metric.sourceKey}</code>}</div>)}
      <h4>{t('okr.snapshotObservations')}</h4>
      {!(snapshot.observations || []).length && <p className="okr-muted">{t('okr.noEvidence')}</p>}
      {(snapshot.observations || []).slice().reverse().map(observation => <div className="okr-version" key={observation.id}>
        <strong>{snapshot.metrics.find(m => m.id === observation.metricId)?.name || t('okr.retiredMetric', { id: observation.metricId })}</strong>
        <time>{date(observation.date)}</time><span>{number(observation.value)}</span><span>{t('okr.source.' + observation.source)}</span><time>{date(observation.capturedAt)}</time><code>{observation.sourceKey}</code>{observation.note && <p>{observation.note}</p>}
      </div>)}
    </div>}
  </details>
}
