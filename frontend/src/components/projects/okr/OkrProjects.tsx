import { useEffect, useRef, useState } from 'react'
import { Button, Input, Modal, Select, Spin } from 'antd'
import { api } from '../../../api'
import { useI18n } from '../../../i18n'
import { useLayout } from '../../../layout'
import { PlusIcon, ChevronRight } from '../../../icons'
import { getHashParams } from '../../../route-hash'
import { pollWhileVisible } from '../../../visible-poll'
import OkrResult from './OkrResult'
import { type OkrOverview } from './okr-workspace'
import './project-okr.css'
import './okr-dashboard.css'

export default function OkrProjects({ projects, loaded, error, retry }: {
  projects: { key: string; name: string; dir: string }[]
  loaded: boolean
  error: boolean
  retry: () => void
}) {
  const { t, locale } = useI18n()
  const { phone } = useLayout()
  const [items, setItems] = useState<OkrOverview[]>([])
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)
  const [creating, setCreating] = useState(false)
  const [project, setProject] = useState<string>()
  const [search, setSearch] = useState('')
  const poll = useRef<ReturnType<typeof pollWhileVisible> | null>(null)
  useEffect(() => {
    const loader = pollWhileVisible(async signal => {
      try {
        const response = await api('GET', '/okr', undefined, { signal })
        if (signal.aborted) return
        const next: OkrOverview[] = response.data || []
        setItems(current => current.length === next.length && current.every((item, i) => item.projectId === next[i].projectId && item.revision === next[i].revision && item.projectName === next[i].projectName) ? current : next)
        setReady(true); setFailed(false)
      } catch (e) { if (!signal.aborted) setFailed(true); throw e }
    }, 30_000)
    poll.current = loader
    return () => { loader.stop(); poll.current = null }
  }, [])
  const query = getHashParams().toString()
  const filter = search.trim().toLocaleLowerCase()
  const shown = items.filter(item => `${item.projectName} ${item.objective}`.toLocaleLowerCase().includes(filter)).slice().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  const available = projects.filter(p => !items.some(item => item.projectId === p.key))
  const day = (date: string) => new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', timeZone: 'Asia/Shanghai' }).format(new Date(date + 'T00:00:00+08:00'))
  return <div className="okr-page okr-dashboard" data-mobile-refresh-scroll>
    <header className="tt-pagehead">{!phone && <h2>{t('okr.title')}</h2>}<div className="acts"><Button type="primary" icon={<PlusIcon />} onClick={() => setCreating(true)} disabled={!ready}>{t('okr.create')}</Button></div></header>
    {items.length > 1 && <Input allowClear aria-label={t('okr.searchObjectives')} placeholder={t('okr.searchObjectives')} value={search} onChange={e => setSearch(e.target.value)} />}
    {failed && <div className="okr-error" role="alert"><p>{t('okr.loadFailed')}</p><Button onClick={() => void poll.current?.refresh()}>{t('inbox.retry')}</Button></div>}
    {!ready && !failed && <Spin />}
    {ready && shown.map(item => <a key={item.projectId} className="okr-objective-link" href={'#/okr/' + encodeURIComponent(item.projectId) + (query ? '?' + query : '')}>
      <div className="okr-objective-meta"><span>{projects.find(p => p.key === item.projectId)?.name || item.projectName}</span><span>{t('okr.shortPeriod', { start: day(item.startDate), end: day(item.endDate) })}</span><ChevronRight size={16} /></div>
      <h2>{item.objective}</h2>
      <div className="okr-results">{item.keyResults.map(kr => <OkrResult key={kr.id} result={kr} compact />)}</div>
    </a>)}
    {ready && !shown.length && <div className="okr-empty"><h2>{t(items.length ? 'okr.noMatchingObjectives' : 'okr.noObjectives')}</h2>{!items.length && <p className="okr-muted">{t('okr.createHint')}</p>}</div>}
    <Modal title={t('okr.create')} open={creating} onCancel={() => setCreating(false)} okText={t('okr.startBuilding')} cancelText={t('common.cancel')} onOk={() => { if (project && available.some(p => p.key === project)) location.hash = '#/okr/' + encodeURIComponent(project) + (query ? '?' + query : '') }} okButtonProps={{ disabled: !project || !available.some(p => p.key === project) }}>
      <p>{t('okr.selectProject')}</p>
      {error && <div role="alert"><p>{t('okr.projectsFailed')}</p><Button onClick={retry}>{t('inbox.retry')}</Button></div>}
      {!loaded ? <Spin /> : available.length ? <Select className="okr-project-select" aria-label={t('okr.selectProject')} showSearch optionFilterProp="label" value={project} onChange={setProject} options={available.map(p => ({ value: p.key, label: p.name }))} /> : <p className="okr-muted">{t(projects.length ? 'okr.allConfigured' : 'okr.noProjects')}</p>}
    </Modal>
  </div>
}
