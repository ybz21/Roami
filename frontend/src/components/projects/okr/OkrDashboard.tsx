import { useI18n } from '../../../i18n'
import { dashboardOf, resultOverview, type Workspace } from './okr-workspace'
import OkrResult from './OkrResult'
import OkrTrend from './OkrTrend'

export default function OkrDashboard({ workspace }: { workspace: Workspace }) {
  const { t } = useI18n()
  const widgets = dashboardOf(workspace).widgets.filter(widget => ['keyResults', 'metricTrend'].includes(widget.type))
  return <section className="okr-dashboard-widgets" aria-label={t('okr.tab.dashboard')}>
    {!widgets.length && <p className="okr-muted">{t('okr.noWidgets')}</p>}
    {widgets.map(widget => widget.type === 'keyResults'
      ? <section className="okr-board" key={widget.id}><h3>{widget.title || t('okr.keyResults')}</h3><div className="okr-results">{workspace.keyResults.filter(kr => !widget.keyResultIds?.length || widget.keyResultIds.includes(kr.id)).map(kr => <OkrResult key={kr.id} result={resultOverview(workspace, kr)} />)}</div></section>
      : <OkrTrend key={widget.id} title={widget.title} workspace={{ ...workspace, metrics: workspace.metrics.filter(metric => !widget.metricIds?.length || widget.metricIds.includes(metric.id)) }} />)}
  </section>
}
