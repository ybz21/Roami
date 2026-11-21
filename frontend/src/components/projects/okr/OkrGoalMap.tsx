import { useI18n } from '../../../i18n'
import OkrResult from './OkrResult'
import { resultOverview, type Initiative, type Workspace } from './okr-workspace'

export default function OkrGoalMap({ workspace }: { workspace: Workspace }) {
  const { t } = useI18n()
  const methods = workspace.initiatives || []
  const method = (item: Initiative) => <article className="okr-map-method" key={item.id}><strong>{item.title}</strong>{item.channel && <small>{item.channel}</small>}{item.description && <p>{item.description}</p>}{item.acceptance && <details><summary>{t('okr.initiativeAcceptance')}</summary><p>{item.acceptance}</p></details>}</article>
  return <section className="okr-goal-map" aria-label={t('okr.goalMap')}>
    <div className="okr-map-objective"><span>O</span><h2>{workspace.objective}</h2></div>
    <ul className="okr-map-results">{workspace.keyResults.map(result => <li key={result.id}>
      <OkrResult result={resultOverview(workspace, result)} compact />
      {methods.some(item => item.keyResultIds.includes(result.id)) && <ul className="okr-map-methods">{methods.filter(item => item.keyResultIds.includes(result.id)).map(item => <li key={item.id}>{method(item)}</li>)}</ul>}
    </li>)}</ul>
    {methods.some(item => !item.keyResultIds.length) && <section className="okr-map-unlinked"><h3>{t('okr.noLinkedResults')}</h3>{methods.filter(item => !item.keyResultIds.length).map(method)}</section>}
  </section>
}
