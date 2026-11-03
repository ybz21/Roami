import { useI18n } from '../../../i18n'
import type { Workspace } from './okr-workspace'

export default function OkrInitiatives({ workspace }: { workspace: Workspace }) {
  const { t } = useI18n()
  return <section className="okr-section">
    <h3>{t('okr.initiatives')}</h3>
    <p className="okr-muted">{t('okr.initiativesHint')}</p>
    {!workspace.initiatives?.length && <p className="okr-muted">{t('okr.noInitiatives')}</p>}
    <div className="okr-initiative-grid">{workspace.initiatives?.map(item => <article className="okr-initiative" key={item.id}>
      <div className="okr-section-head"><h4>{item.title}</h4>{item.channel && <span className="okr-muted">{item.channel}</span>}</div>
      {item.description && <p>{item.description}</p>}
      <div className="okr-muted">{t('okr.linkedResults')}{item.keyResultIds.length ? <ul>{item.keyResultIds.map(id => <li key={id}>{workspace.keyResults.find(result => result.id === id)?.title || t('okr.unnamedResult')}</li>)}</ul> : <p>{t('okr.noLinkedResults')}</p>}</div>
      {item.acceptance && <details><summary>{t('okr.initiativeAcceptance')}</summary><p>{item.acceptance}</p></details>}
    </article>)}</div>
  </section>
}
