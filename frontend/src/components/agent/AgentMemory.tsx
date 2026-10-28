import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { App, Button, Dropdown, Input, Select } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { ChevronLeft, GearIcon, MoreIcon, OpenInIcon, SearchIcon } from '../../icons'
import MobileSubPage from '../MobileSubPage'
import { api } from '../../api'
import { useAgentData } from './useAgentData'
import { memoryEventScope, publishMemoryChanges, subscribeMemoryChanges } from './agent-memory-events'
import { useMemoryCatalog } from './useMemoryCatalog'
import { useMemoryRoute } from './memory-browser-route'
import { dailyMemory, memoryScope, type MemoryDetail as Detail, type MemoryRecord, type MemoryScope } from './memory-record'
import { agentPagePath } from './agent-page-route'
import MemoryList from './MemoryList'
import MemoryDetail from './MemoryDetail'
import './memory-browser.css'

const positions = new Map<string, number>()
function rememberScroll(key: string, value: number) { positions.delete(key); positions.set(key, value); if (positions.size > 64) positions.delete(positions.keys().next().value) }
function localDay(timezone: string) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  return ['year', 'month', 'day'].map(name => parts.find(part => part.type === name)?.value).join('-')
}
export default function AgentMemory({ cid = '', projects, select, fullPage = false, embedded = false, compact = false, defaultGroup = 'all', onBack }: {
  cid?: string; projects: { id: string; name: string }[]; select: (cid: string, branch?: string, message?: string) => void
  fullPage?: boolean; embedded?: boolean; compact?: boolean; defaultGroup?: MemoryScope; onBack?: () => void
}) {
  const { t, locale } = useI18n(), { phone } = useLayout(), { message, modal } = App.useApp()
  const navigation = useMemoryRoute(defaultGroup), route = navigation.value
  const catalog = useMemoryCatalog(route, cid, defaultGroup === 'conversation')
  const status = useAgentData<{ memoryTimezone: string }>('/agent/status', 60_000)
  const detailPath = route.id ? '/agent/memories/' + encodeURIComponent(route.id) + '/detail' : null
  const detail = useAgentData<Detail>(detailPath, 5000)
  const [filters, setFilters] = useState(false), [busy, setBusy] = useState(false), [mobileMenu, setMobileMenu] = useState(false), [mutationError, setMutationError] = useState(''), [revision, setRevision] = useState(0)
  const busyRef = useRef(false), alive = useRef(true), currentScope = useRef(catalog.scope), currentId = useRef(route.id)
  currentScope.current = catalog.scope; currentId.current = route.id
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const refresh = useRef(() => {})
  refresh.current = () => { catalog.refresh(); catalog.facets.refresh(); detail.refresh(); setRevision(value => value + 1) }
  useEffect(() => subscribeMemoryChanges(() => refresh.current()), [catalog.scope])
  useEffect(() => { setMutationError(''); setMobileMenu(false) }, [route.id, catalog.scope])
  const items = catalog.value?.items || [], total = catalog.value?.total || 0
  const record = detail.value?.record?.id === route.id ? detail.value.record : items.find(item => item.id === route.id)
  const data = detail.value?.record?.id === route.id ? detail.value : undefined
  const missing = ['MEMORY_NOT_FOUND', 'MEMORY_SOURCE_NOT_FOUND'].includes(detail.errorCode || '')
  const timezone = record?.timezone || status.value?.memoryTimezone || 'UTC'
  const date = (value: number | string, full = false) => new Intl.DateTimeFormat(locale, { timeZone: timezone, month: 'short', day: 'numeric', ...(full ? { year: 'numeric', hour: '2-digit', minute: '2-digit' } as const : {}) }).format(new Date(value))
  const scope = (item: MemoryRecord) => {
    const daily = dailyMemory(item), project = item.project_id || daily?.scopeKey
    if (daily) return !project || project === 'unassigned' ? t('agent.memoryUnassigned') : projects.find(p => p.id === project)?.name || t('agent.memoryBrowse.projectUnavailable')
    const kind = memoryScope(item)
    if (kind === 'personal') return t('agent.memoryBrowse.personal')
    const name = kind === 'project' ? projects.find(p => p.id === item.project_id)?.name : kind === 'task' ? item.task_title : item.conversation_title
    return t('agent.memoryScope.' + kind, { name: name || t('agent.memoryBrowse.' + kind + 'Unavailable') })
  }
  const scroll = useRef<HTMLDivElement>(null), scrollKey = catalog.scope + ':' + route.view + ':' + route.scope + ':' + route.entity + ':' + route.kind + ':' + route.query + ':' + route.page + ':' + route.date
  const saveScroll = () => { if (!route.id && scroll.current) rememberScroll(scrollKey, scroll.current.scrollTop) }
  useLayoutEffect(() => { if (scroll.current && !route.id) scroll.current.scrollTop = positions.get(scrollKey) || 0 }, [scrollKey, route.id, catalog.value])
  const choose = (id: string) => { if (scroll.current) rememberScroll(scrollKey, scroll.current.scrollTop); navigation.change({ id }, true) }
  const clear = () => navigation.change({ query: '', scope: 'all', kind: 'all', entity: '', page: 0, date: '', id: '' })
  const mutate = async (item: MemoryRecord, suffix: string, body?: unknown) => {
    if (busyRef.current) return false
    busyRef.current = true; setBusy(true); setMutationError('')
    const eventScope = memoryEventScope(), ownedScope = currentScope.current
    try {
      await api(body ? 'POST' : 'DELETE', '/agent/memories/' + encodeURIComponent(item.id) + suffix, body)
      publishMemoryChanges(eventScope)
      if (alive.current && currentScope.current === ownedScope) {
        if (currentId.current === item.id) navigation.back()
        message.success(t(body ? 'agent.memoryBrowse.reviewed' : 'agent.memoryBrowse.removed'))
      }
      return true
    } catch (error: any) {
      if (alive.current && currentScope.current === ownedScope) setMutationError(t(['MEMORY_CURRENT_CHANGED', 'MEMORY_CANDIDATE_ALREADY_RESOLVED'].includes(error?.apiError?.code) ? 'agent.memoryBrowse.currentChanged' : error?.apiError?.code === 'MEMORY_SOURCE_CHANGED' || error?.apiError?.code === 'MEMORY_FORGOTTEN' ? 'agent.memoryBrowse.sourceChanged' : 'agent.requestFailed'))
      return false
    } finally { busyRef.current = false; if (alive.current) setBusy(false) }
  }
  const confirm = async () => {
    if (!record || !data?.canConfirm) return
    const body = { accepted: true, expectedCurrentId: data.currentVersionId ?? data.current?.id ?? '' }
    if (data.current && data.current.body !== record.body) {
      modal.confirm({ title: t('agent.memoryBrowse.replace'), content: t('agent.memoryBrowse.replaceHint'), okText: t('agent.memoryBrowse.replace'), cancelText: t('common.cancel'), onOk: async () => { if (!await mutate(record, '/confirm', body)) throw new Error('MEMORY_CONFIRM_FAILED') } })
    } else await mutate(record, '/confirm', body)
  }
  const remove = (forget: boolean) => {
    if (!record) return
    modal.confirm({ title: t(forget ? 'agent.memoryForgetTitle' : 'agent.memoryDelete'), content: t(forget ? 'agent.memoryForgetBody' : 'agent.memoryDeleteConfirm'), okText: t(forget ? 'agent.memoryForget' : 'agent.memoryDelete'), cancelText: t('common.cancel'), okButtonProps: { danger: true }, onOk: async () => { if (!await mutate(record, '?forgetSources=' + forget)) throw new Error('MEMORY_DELETE_FAILED') } })
  }
  const menu = { items: [{ key: 'delete', label: t('agent.memoryDelete'), danger: true }, { key: 'forget', label: t('agent.memoryForget'), danger: true }], onClick: ({ key }: { key: string }) => { setMobileMenu(false); remove(key === 'forget') } }
  const more = record?.state === 'active' && !missing && <Dropdown trigger={['click']} menu={menu}><button type="button" className="memory-icon tt-act" disabled={busy} aria-label={t('agent.memoryMore', { title: record.title })}><MoreIcon size={20} /></button></Dropdown>
  const panel = !fullPage || phone
  const entityKind = route.view === 'activity' ? 'project' : route.scope
  const options = ['project', 'conversation', 'task'].includes(entityKind) ? (catalog.facets.value?.[entityKind] || []).map(item => ({ value: item.id, label: entityKind === 'project' ? projects.find(p => p.id === item.id)?.name || t('agent.memoryBrowse.projectUnavailable') : item.name || t('agent.memoryBrowse.' + entityKind + 'Unavailable') })) : []
  if (route.entity && !options.some(option => option.value === route.entity)) options.push({ value: route.entity, label: t('agent.memoryBrowse.entityUnavailable') })
  const filtered = !!(route.query || route.scope !== 'all' || route.entity || route.kind !== 'all' || route.date)
  const list = <section className="memory-list-pane" aria-label={t('agent.memory')}>
    <div className="memory-tabs" role="tablist" aria-label={t('agent.memory')}>
      {(['saved', 'review', 'activity'] as const).map(view => <button type="button" role="tab" aria-selected={route.view === view} key={view} onClick={() => navigation.change({ view, id: '', page: 0, entity: '', query: '', date: '' })}>{t(view === 'activity' ? 'agent.memoryView.activity' : 'agent.memoryBrowse.' + view)}{view === 'review' && (catalog.facets.value?.reviewCount || 0) > 0 && <span className="memory-number">{new Intl.NumberFormat(locale).format(catalog.facets.value.reviewCount)}</span>}</button>)}
      {compact && <a className="memory-icon tt-act" href={'#/' + agentPagePath('memory', cid ? 'home/' + encodeURIComponent(cid) : 'home') + (location.hash.includes('?') ? '?' + location.hash.split('?')[1] : '')} aria-label={t('agent.memoryBrowse.browse')}><OpenInIcon size={18} /></a>}
    </div>
    <div className="memory-searchbar"><Input type="search" allowClear maxLength={1000} value={route.query} onChange={event => navigation.change({ query: event.target.value, page: 0, id: '' })} prefix={<SearchIcon size={18} />} placeholder={t('agent.searchMemory')} aria-label={t('agent.searchMemory')} /><button type="button" className="memory-icon tt-act" aria-expanded={filters} data-active={route.kind !== 'all' || !!route.date} aria-label={t('agent.memoryBrowse.filters')} onClick={() => setFilters(value => !value)}><GearIcon size={18} /></button></div>
    <div className="memory-filterbar">
      {route.view !== 'activity' && <Select aria-label={t('agent.memoryBrowse.scope')} value={route.scope} onChange={scope => navigation.change({ scope, entity: '', page: 0, id: '' })} options={(['all', 'personal', 'project', 'conversation', 'task'] as MemoryScope[]).map(value => ({ value, label: t(value === 'all' ? 'agent.memoryBrowse.allScopes' : value === 'personal' ? 'agent.memoryBrowse.personal' : 'agent.memoryGroup.' + value) }))} />}
      {(route.view === 'activity' || ['project', 'conversation', 'task'].includes(route.scope)) && <Select loading={catalog.facets.loading} showSearch optionFilterProp="label" aria-label={t('agent.memoryGroup.' + entityKind)} value={route.entity} onChange={entity => navigation.change({ entity, page: 0, id: '' })} options={[{ value: '', label: t(entityKind === 'project' ? 'agent.memoryBrowse.allProjects' : 'agent.memoryGroup.all') }, ...options]} />}
    </div>
    {filters && <div className="memory-filters">{route.view !== 'activity' ? <label>{t('agent.memoryBrowse.type')}<Select aria-label={t('agent.memoryBrowse.type')} value={route.kind} onChange={kind => navigation.change({ kind, page: 0, id: '' })} options={['all', 'preference', 'decision', 'fact', 'summary'].map(value => ({ value, label: t(value === 'all' ? 'agent.memoryBrowse.allTypes' : 'agent.memoryKind.' + value) }))} /></label> : <label>{t('agent.memoryDate')}<Input type="date" aria-label={t('agent.memoryDate')} value={route.date} onChange={event => navigation.change({ date: event.target.value, page: 0, id: '' })} /></label>}{route.view === 'activity' && <button type="button" className="tt-act" disabled={!status.value?.memoryTimezone} onClick={() => navigation.change({ date: localDay(status.value.memoryTimezone), page: 0, id: '' })}>{t('agent.memoryToday')}</button>}<button type="button" className="tt-act" onClick={clear}>{t('agent.memoryBrowse.clear')}</button></div>}
    {catalog.failed && <div className="memory-alert" role="alert"><p>{t('agent.memoryBrowse.loadFailed')}</p><Button onClick={catalog.refresh}>{t('agent.retry')}</Button></div>}
    {catalog.facets.failed && <div className="memory-alert" role="alert"><p>{t('agent.memoryBrowse.filtersFailed')}</p><Button onClick={catalog.facets.refresh}>{t('agent.retry')}</Button></div>}
    <MemoryList activity={route.view === 'activity'} items={items} loading={catalog.loading} failed={catalog.failed} selected={route.id} total={total} page={route.page} date={date} scope={scope} choose={choose} changePage={page => navigation.change({ page, id: '' })} filtered={filtered} clear={clear} scroll={scroll} onScroll={saveScroll} />
  </section>
  const body = <div className={`memory-browser${route.id ? ' has-selection' : ''}${panel ? ' is-panel' : ''}`}>
    {list}<section className="memory-detail-pane" aria-label={t('agent.memoryBrowse.detail')}>
      {mutationError && <div className="memory-alert" role="alert"><p>{mutationError}</p><Button onClick={() => { setMutationError(''); detail.refresh() }}>{t('agent.retry')}</Button></div>}
      <MemoryDetail id={route.id} record={record} data={data} loading={detail.loading} failed={detail.failed} missing={missing} retry={detail.refresh} scope={scope} date={date} select={select} panel={panel} back={navigation.back} more={more} busy={busy} confirm={confirm} reject={() => record && mutate(record, '/confirm', { accepted: false })} revision={revision} />
    </section>
  </div>
  if (phone && fullPage && onBack) return <>{record?.state === 'active' && !missing && <Dropdown open={mobileMenu} onOpenChange={setMobileMenu} menu={menu} trigger={['click']}><span className="memory-mobile-menu-anchor" /></Dropdown>}<MobileSubPage title={route.id ? t(record?.day_key ? 'agent.memoryBrowse.activityDetail' : 'agent.memoryBrowse.detail') : t('agent.memory')} manageHistory={false} keepBottomNav search={false} onBack={route.id ? navigation.back : onBack} action={record?.state === 'active' && !missing ? { label: t('agent.memoryMore', { title: record.title }), icon: <MoreIcon size={20} />, onClick: () => setMobileMenu(value => !value) } : undefined}>{body}</MobileSubPage></>
  if (fullPage) return <section className="memory-page">{!embedded && <header className="tt-pagehead"><div className="ttl"><h2>{t('agent.memory')}</h2></div>{onBack && <div className="acts"><button type="button" className="tt-act" onClick={onBack}><ChevronLeft size={18} />{t('common.back')}</button></div>}</header>}{body}</section>
  return <div className={compact ? 'memory-panel' : 'memory-dialog'}>{body}</div>
}
