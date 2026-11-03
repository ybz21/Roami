import { useState } from 'react'
import { Button, Input, Spin } from 'antd'
import { useI18n } from '../../../i18n'
import { useLayout } from '../../../layout'
import { ChevronRight, TargetIcon } from '../../../icons'
import { getHashParams } from '../../../route-hash'
import './project-okr.css'

export default function OkrProjects({ projects, loaded, error, retry }: {
  projects: { key: string; name: string; dir: string }[]
  loaded: boolean
  error: boolean
  retry: () => void
}) {
  const { t } = useI18n()
  const { phone } = useLayout()
  const [search, setSearch] = useState('')
  const query = getHashParams().toString()
  const filter = search.trim().toLocaleLowerCase()
  const shown = projects.filter(p => `${p.name} ${p.dir}`.toLocaleLowerCase().includes(filter))
  return <div className="okr-page" data-mobile-refresh-scroll>
    {!phone && <header className="tt-pagehead"><h2>{t('okr.title')}</h2></header>}
    <section className="okr-section">
      <p className="okr-muted">{t('okr.chooseProject')}</p>
      <Input allowClear aria-label={t('okr.searchProjects')} placeholder={t('okr.searchProjects')} value={search} onChange={e => setSearch(e.target.value)} />
    </section>
    {error && <div className="okr-error" role="alert"><p>{t('okr.projectsFailed')}</p><Button onClick={retry}>{t('inbox.retry')}</Button></div>}
    {!loaded && !error && <Spin />}
    {loaded && shown.map(project => <a key={project.key} className="okr-project-link" href={'#/okr/' + encodeURIComponent(project.key) + (query ? '?' + query : '')}>
      <TargetIcon /><span><b>{project.name}</b><small>{project.dir}</small></span><ChevronRight />
    </a>)}
    {loaded && !shown.length && <p className="okr-muted">{t(projects.length ? 'okr.noMatchingProjects' : 'okr.noProjects')}</p>}
  </div>
}
