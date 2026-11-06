import { Suspense } from 'react'
import { lazyRetry } from '../../lazy-retry'
import { Spin } from 'antd'
import { useI18n } from '../../../i18n'
import { dashboardOf, resultOverview, type Workspace } from './okr-workspace'
import OkrResult from './OkrResult'
import OkrTrend from './OkrTrend'

const OkrHtmlDashboard = lazyRetry(() => import('./OkrHtmlDashboard'))

export default function OkrDashboard({ workspace, active = true, onRefresh }: { workspace: Workspace; active?: boolean; onRefresh?: () => void }) {
  const { t } = useI18n()
  if (workspace.dashboard?.html) return <Suspense fallback={<Spin />}><OkrHtmlDashboard workspace={workspace} active={active} onRefresh={onRefresh} /></Suspense>
  const widgets = dashboardOf(workspace).widgets.filter(widget => ['keyResults', 'metricTrend'].includes(widget.type))
  const cards = widgets.flatMap(widget => {
    if (widget.type === 'keyResults') {
      const results = workspace.keyResults.filter(kr => !widget.keyResultIds?.length || widget.keyResultIds.includes(kr.id))
      return results.length ? [<section className="okr-board" key={widget.id}><h3>{widget.title || t('okr.keyResults')}</h3><div className="okr-results">{results.map(kr => <OkrResult key={kr.id} result={resultOverview(workspace, kr)} />)}</div></section>] : []
    }
    const metrics = workspace.metrics.filter(metric => !widget.metricIds?.length || widget.metricIds.includes(metric.id))
    return metrics.length ? [<div className="okr-trend-grid" key={widget.id}>{metrics.map(metric => <OkrTrend key={metric.id} title={metrics.length === 1 ? widget.title || metric.name : metric.name} workspace={{ ...workspace, metrics: [metric] }} />)}</div>] : []
  })
  return <section className="okr-dashboard-widgets" aria-label={t('okr.tab.dashboard')}>
    {!cards.length && <p className="okr-muted">{t('okr.noWidgets')}</p>}
    {cards}
  </section>
}
