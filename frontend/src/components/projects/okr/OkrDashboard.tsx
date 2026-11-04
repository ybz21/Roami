import { Button } from 'antd'
import { useI18n } from '../../../i18n'
import { dashboardOf, resultOverview, type Workspace } from './okr-workspace'
import OkrResult from './OkrResult'
import OkrTrend from './OkrTrend'

export default function OkrDashboard({ workspace, onReview, onConfigure, onSource }: { workspace: Workspace; onReview: () => void; onConfigure: () => void; onSource?: (metricId: string) => void }) {
  const { t } = useI18n()
  const latestReview = workspace.reviews.slice(-1)[0]
  const widgets = dashboardOf(workspace).widgets
  return <section className="okr-dashboard-widgets" aria-label={t('okr.tab.dashboard')}>
    {!widgets.length && <div className="okr-empty"><p className="okr-muted">{t('okr.noWidgets')}</p><Button onClick={onConfigure}>{t('okr.dashboardConfiguration')}</Button></div>}
    {widgets.map(widget => {
      if (widget.type === 'keyResults') return <section className="okr-board" key={widget.id}><h3>{widget.title || t('okr.keyResults')}</h3><div className="okr-results">{workspace.keyResults.filter(kr => !widget.keyResultIds?.length || widget.keyResultIds.includes(kr.id)).map(kr => <OkrResult key={kr.id} result={resultOverview(workspace, kr)} />)}</div></section>
      if (widget.type === 'metricTrend') return <OkrTrend key={widget.id} title={widget.title} workspace={{ ...workspace, metrics: workspace.metrics.filter(metric => !widget.metricIds?.length || widget.metricIds.includes(metric.id)) }} />
      if (widget.type === 'nextAction') return <section className="okr-focus" key={widget.id}><h3>{widget.title || t('okr.nextAction')}</h3>{latestReview ? <><p className="okr-focus-action">{latestReview.actions || latestReview.summary}</p><Button onClick={onReview}>{t('okr.openReview')}</Button></> : <><p className="okr-muted">{t('okr.noReviewAction')}</p><Button onClick={onReview}>{t('okr.writeFirstReview')}</Button></>}</section>
      return null
    })}
    <section className="okr-section okr-data-sources"><h3>{t('okr.dataSources')}</h3>{workspace.metrics.map(metric => <article key={metric.id} className="okr-data-source"><div><strong>{metric.name}</strong><p className="okr-muted">{metric.source === 'github' ? t('okr.githubSource', { repo: metric.repo || '', field: t('okr.github.' + metric.field) }) : t('okr.source.manual')}</p></div><Button onClick={() => onSource ? onSource(metric.id) : onConfigure()}>{t('okr.configureSource')}</Button></article>)}</section>
  </section>
}
