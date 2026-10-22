import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { App, Button, Dropdown, Input, Select, Skeleton } from 'antd'
import { I18nProvider, useI18n } from '../src/i18n'
import { ThemeProvider, useThemeMode } from '../src/theme'
import { useLayout } from '../src/layout'
import { AppsIcon, BellIcon, CheckIcon, ChevronLeft, ChevronRight, ClockIcon, FolderIcon, GearIcon, HomeIcon, MoreIcon, NotebookIcon, OpenInIcon, SearchIcon } from '../src/icons'
import MobileSubPage from '../src/components/MobileSubPage'
import { examples, activityExamples, type MemoryExample } from './memory-browser-data'
import '../src/index.css'
import '../src/mobile-material.css'
import './memory-browser.css'

type View = 'saved' | 'review' | 'activity'
type Route = { view: View; scope: string; entity: string; kind: string; query: string; id: string; source: boolean }
function readRoute(): Route {
  const params = new URLSearchParams(location.hash.split('?')[1] || '')
  return { view: (params.get('view') || 'saved') as View, scope: params.get('scope') || 'all', entity: params.get('entity') || 'all', kind: params.get('kind') || 'all', query: params.get('q') || '', id: params.get('id') || '', source: params.get('source') === '1' }
}
function Prototype() {
  const { t, locale, setLocale } = useI18n(), { setMode } = useThemeMode(), { phone } = useLayout()
  const { modal, message } = App.useApp()
  const [route, setRoute] = useState(() => { const value = readRoute(); if (!phone && !location.hash) value.id = 'codex'; return value }), [records, setRecords] = useState(examples)
  const [mode, setViewMode] = useState('library'), [filters, setFilters] = useState(false), [scenario, setScenario] = useState('normal')
  const [sourceChanged, setSourceChanged] = useState(false), [mobileMenu, setMobileMenu] = useState(false)
  const listRef = useRef<HTMLDivElement>(null), listPosition = useRef(0)
  const routeRef = useRef(route), controls = useRef({ setLocale, setMode })
  routeRef.current = route; controls.current = { setLocale, setMode }
  const navigate = (patch: Partial<Route>, push = false) => {
    const next = { ...routeRef.current, ...patch }
    const p = new URLSearchParams({ view: next.view, scope: next.scope, entity: next.entity, kind: next.kind })
    if (next.query) p.set('q', next.query)
    if (next.id) p.set('id', next.id)
    if (next.source) p.set('source', '1')
    history[push ? 'pushState' : 'replaceState'](push ? { memoryDesign: true } : history.state || {}, '', location.href.split('#')[0] + '#/memory?' + p)
    routeRef.current = next; setRoute(next)
  }
  useEffect(() => {
    const change = () => { setRoute(readRoute()) }
    const settings = (event: MessageEvent) => {
      if (event.source !== window.parent || event.data?.type !== 'memory-design-settings') return
      const data = event.data
      if (data.theme) controls.current.setMode(data.theme)
      if (data.locale) controls.current.setLocale(data.locale)
      if (data.mode) setViewMode(data.mode)
      if (data.scenario) { setScenario(data.scenario); if (data.scenario === 'empty') navigate({ id: '', source: false }) }
      if (data.device) navigate({ id: '', source: false })
      if (data.sourceChanged !== undefined) setSourceChanged(data.sourceChanged)
    }
    window.addEventListener('hashchange', change); window.addEventListener('popstate', change)
    window.addEventListener('message', settings)
    window.parent.postMessage({ type: 'memory-design-ready' }, '*')
    return () => { window.removeEventListener('hashchange', change); window.removeEventListener('popstate', change); window.removeEventListener('message', settings) }
  }, [])
  useLayoutEffect(() => { if (!route.id && listRef.current) listRef.current.scrollTop = listPosition.current }, [route.id])
  const format = (value: string, full = false) => new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', ...(full ? { hour: '2-digit', minute: '2-digit' } as const : {}), timeZone: 'Asia/Shanghai' }).format(new Date(value))
  const scopeLabel = (item: MemoryExample) => item.scope === 'personal' ? t('agent.memoryBrowse.personal') : t('agent.memoryScope.' + item.scope, { name: item.scopeName || '' })
  const missingSource = scenario === 'source-missing'
  const selected = records.find(item => item.id === route.id)
  const activity = activityExamples.find(item => item.id === route.id)
  const matches = (text: string) => text.toLocaleLowerCase(locale).includes(route.query.trim().toLocaleLowerCase(locale))
  const shown = scenario === 'empty' ? [] : records.filter(item => (route.view === 'saved' ? item.state === 'active' : item.state !== 'active') && (route.scope === 'all' || item.scope === route.scope) && (route.entity === 'all' || item.scopeName === route.entity) && (route.kind === 'all' || item.kind === route.kind) && matches(item.title + item.body + scopeLabel(item)))
  const days = scenario === 'empty' ? [] : activityExamples.filter(item => matches(item.project))
  const entities = [...new Set(records.filter(item => item.scope === route.scope && item.scopeName).map(item => item.scopeName!))]
  const reviewCount = records.filter(item => item.state !== 'active').length
  const choose = (id: string) => { listPosition.current = listRef.current?.scrollTop || 0; navigate({ id, source: false }, true) }
  const back = () => {
    if (route.source || route.id) { if (history.state?.memoryDesign) history.back(); else navigate(route.source ? { source: false } : { id: '', source: false }); return }
    navigate({ id: '', query: '', scope: 'all', entity: 'all', kind: 'all' })
  }
  const clear = () => navigate({ query: '', scope: 'all', entity: 'all', kind: 'all' })
  const review = (item: MemoryExample, accept: boolean) => {
    const apply = () => {
      setRecords(previous => previous.filter(record => record.id !== item.id && !(accept && item.state === 'conflict' && record.id === 'codex')).concat(accept ? [{ ...item, state: 'active', current: undefined }] : []))
      navigate({ id: '', source: false }); message.success(t(accept ? 'agent.memoryBrowse.reviewed' : 'agent.memoryBrowse.removed'))
    }
    if (accept && item.state === 'conflict') modal.confirm({ title: t('agent.memoryBrowse.replace'), content: t('agent.memoryBrowse.replaceHint'), okText: t('agent.memoryBrowse.replace'), cancelText: t('common.cancel'), onOk: apply })
    else apply()
  }
  const remove = (item: MemoryExample, forget: boolean) => modal.confirm({
    title: t(forget ? 'agent.memoryForgetTitle' : 'agent.memoryDelete'),
    content: t(forget ? 'agent.memoryForgetBody' : 'agent.memoryDeleteConfirm'),
    okText: t(forget ? 'agent.memoryForget' : 'agent.memoryDelete'), cancelText: t('common.cancel'), okButtonProps: { danger: true },
    onOk: () => { setRecords(items => items.filter(record => record.id !== item.id)); navigate({ id: '', source: false }); message.success(t('agent.memoryBrowse.removed')) },
  })
  const menu = selected ? { items: [{ key: 'delete', label: t('agent.memoryDelete'), danger: true }, { key: 'forget', label: t('agent.memoryForget'), danger: true }], onClick: ({ key }: { key: string }) => remove(selected, key === 'forget') } : undefined
  const more = selected && <Dropdown trigger={['click']} menu={menu}><button type="button" className="mdb-icon tt-act" aria-label={t('agent.memoryMore', { title: selected.title })}><MoreIcon size={20} /></button></Dropdown>
  const tabs = <div className="mdb-tabs" role="tablist" aria-label={t('agent.memory')}>
    {(['saved', 'review', 'activity'] as View[]).map(view => <button type="button" role="tab" aria-selected={route.view === view} key={view} onClick={() => navigate({ view, id: '', source: false, query: '' })}>{t(view === 'activity' ? 'agent.memoryView.activity' : 'agent.memoryBrowse.' + view)}{view === 'review' && reviewCount > 0 && <span className="mdb-number">{new Intl.NumberFormat(locale).format(reviewCount)}</span>}</button>)}
  </div>
  const list = <section className="mdb-list-pane" aria-label={t('agent.memory')}>
    {tabs}
    <div className="mdb-searchbar"><Input type="search" aria-label={t('agent.searchMemory')} placeholder={t('agent.searchMemory')} prefix={<SearchIcon size={18} />} allowClear value={route.query} onChange={event => navigate({ query: event.target.value, id: '', source: false })} /><button type="button" className="mdb-icon tt-act" aria-label={t('agent.memoryBrowse.filters')} aria-expanded={filters} data-active={route.scope !== 'all' || route.kind !== 'all'} onClick={() => setFilters(value => !value)}><GearIcon size={18} /></button></div>
    {route.view !== 'activity' && <div className="mdb-filterbar"><Select aria-label={t('agent.memoryBrowse.scope')} value={route.scope} onChange={scope => navigate({ scope, entity: 'all', id: '', source: false })} options={['all', 'personal', 'project', 'conversation', 'task'].map(value => ({ value, label: t(value === 'all' ? 'agent.memoryBrowse.allScopes' : value === 'personal' ? 'agent.memoryBrowse.personal' : 'agent.memoryGroup.' + value) }))} />{['project', 'conversation', 'task'].includes(route.scope) && <Select aria-label={t('agent.memoryGroup.' + route.scope)} value={route.entity} onChange={entity => navigate({ entity, id: '', source: false })} options={[{ value: 'all', label: t('agent.memoryGroup.all') }, ...entities.map(value => ({ value, label: value }))]} />}{!filters && route.kind !== 'all' && <button type="button" className="tt-act" onClick={() => navigate({ kind: 'all' })}>{t('agent.memoryKind.' + route.kind)}<CheckIcon size={14} /></button>}</div>}
    {filters && <div className="mdb-filters"><label>{t('agent.memoryBrowse.type')}<Select aria-label={t('agent.memoryBrowse.type')} value={route.kind} disabled={route.view === 'activity'} onChange={kind => navigate({ kind, id: '', source: false })} options={['all', 'preference', 'decision', 'fact', 'summary'].map(value => ({ value, label: t(value === 'all' ? 'agent.memoryBrowse.allTypes' : 'agent.memoryKind.' + value) }))} /></label><button type="button" className="tt-act" onClick={clear}>{t('agent.memoryBrowse.clear')}</button></div>}
    {scenario === 'error' && <div className="mdb-alert" role="alert"><p>{t('agent.memoryBrowse.loadFailed')}</p><Button onClick={() => setScenario('normal')}>{t('agent.retry')}</Button></div>}
    <div className="mdb-list-scroll" ref={listRef} aria-busy={scenario === 'loading'}>
      {scenario === 'loading' ? <div className="mdb-loading"><Skeleton active /><Skeleton active /></div> : route.view === 'activity' ? days.map((item, index) => <React.Fragment key={item.id}>{(!index || days[index - 1].date !== item.date) && <h3 className="mdb-day">{format(item.date)}</h3>}<button type="button" className="mdb-row" aria-current={route.id === item.id} onClick={() => choose(item.id)}><span className="mdb-row-head"><strong>{item.project}</strong><ChevronRight size={16} /></span><span className="mdb-row-summary">{t('agent.memoryBrowse.activitySummary', { turns: item.turns, completed: item.completed })}</span></button></React.Fragment>) : shown.map(item => <button type="button" className="mdb-row" aria-current={route.id === item.id} key={item.id} onClick={() => choose(item.id)}><span className="mdb-row-head"><strong>{item.title}</strong>{item.state === 'conflict' ? <span className="mdb-warning">{t('agent.memoryBrowse.conflict')}</span> : <ChevronRight size={16} />}</span><span className="mdb-row-summary">{item.body}</span><span className="mdb-row-meta"><span>{scopeLabel(item)}</span><time dateTime={item.updated}>{format(item.updated)}</time></span></button>)}
      {scenario !== 'loading' && !(route.view === 'activity' ? days.length : shown.length) && <div className="mdb-empty"><NotebookIcon size={24} /><p>{t('agent.memoryBrowse.noResults')}</p>{(route.query || route.scope !== 'all' || route.kind !== 'all') && <Button onClick={clear}>{t('agent.memoryBrowse.clear')}</Button>}</div>}
    </div>
  </section>
  const detail = selected ? <>
    {!phone && <div className="mdb-detailbar">{mode === 'rail' && <button type="button" className="tt-act" onClick={back}><ChevronLeft size={18} />{t('common.back')}</button>}<span>{t(route.source ? 'agent.memoryBrowse.sourceConversation' : 'agent.memoryBrowse.detail')}</span>{more}</div>}
    <div className="mdb-detail-scroll">
      {route.source ? <article className="mdb-reading"><div className="mdb-kicker">{t('agent.memoryBrowse.sourceConversation')}</div><h2>{selected.conversation}</h2><p className="mdb-muted">{format(selected.updated, true)}</p><div className="mdb-original"><span className="mdb-muted">{t('agent.memorySource.message.accepted')}</span><p>{selected.quote}</p></div><button type="button" className="tt-act" onClick={() => navigate({ source: false })}><ChevronLeft size={16} />{t('agent.memoryBrowse.detail')}</button></article> : <article className="mdb-reading">
        <div className="mdb-kicker"><span>{t('agent.memoryKind.' + selected.kind)}</span><span className={selected.state !== 'active' ? 'mdb-warning' : ''}>{t(selected.state === 'active' ? 'agent.memoryBrowse.saved' : selected.state === 'conflict' ? 'agent.memoryBrowse.conflict' : 'agent.memoryBrowse.review')}</span></div>
        <h2>{selected.title}</h2>
        {selected.current ? <div className="mdb-comparison"><section><h3>{t('agent.memoryBrowse.current')}</h3><p>{selected.current}</p></section><section><h3>{t('agent.memoryBrowse.proposed')}</h3><p>{selected.body}</p></section></div> : <p className="mdb-full-body">{selected.body}</p>}
        {selected.state !== 'active' && <p className="mdb-review-note">{t('agent.memoryBrowse.reviewHint')}</p>}
        <section className="mdb-detail-section"><h3>{t('agent.memoryBrowse.scope')}</h3><strong>{scopeLabel(selected)}</strong><p className="mdb-muted">{t('agent.memoryBrowse.' + selected.scope + 'Hint')}</p></section>
        <section className="mdb-detail-section"><h3>{t('agent.memoryBrowse.source')}</h3><div className="mdb-source-heading"><NotebookIcon size={18} /><strong>{selected.conversation}</strong></div><time className="mdb-muted" dateTime={selected.updated}>{format(selected.updated, true)}</time>{missingSource ? <p className="mdb-muted">{t('agent.memorySourceMissing')}</p> : <blockquote>{selected.quote}</blockquote>}{sourceChanged && <p className="mdb-warning">{t('agent.memoryBrowse.sourceChanged')}</p>}<button type="button" className="tt-act" disabled={missingSource} onClick={() => navigate({ source: true }, true)}>{t('agent.memoryOpenSource')}<OpenInIcon size={16} /></button></section>
        <section className="mdb-detail-section mdb-changes"><details><summary>{t('agent.memoryBrowse.history')}<ChevronRight size={16} /></summary><div className="mdb-history-entry"><ClockIcon size={16} /><div><strong>{t('agent.memoryBrowse.saved')}</strong><p>{format(selected.updated, true)}</p></div></div>{selected.merged && <div className="mdb-history-entry"><CheckIcon size={16} /><div><strong>{t('agent.memoryBrowse.merged')}</strong><p>{selected.quote}</p></div></div>}</details></section>
      </article>}
    </div>
    {selected.state !== 'active' && !route.source && <footer className="mdb-detail-actions"><Button onClick={() => review(selected, false)}>{t('agent.memoryReject')}</Button><Button type="primary" disabled={sourceChanged || missingSource} onClick={() => review(selected, true)}>{t(selected.state === 'conflict' ? 'agent.memoryBrowse.replace' : 'agent.memoryConfirm')}</Button></footer>}
  </> : activity ? <><div className="mdb-detailbar">{mode === 'rail' && <button type="button" className="tt-act" onClick={back}><ChevronLeft size={18} />{t('common.back')}</button>}<span>{t('agent.memoryBrowse.activityDetail')}</span></div><div className="mdb-detail-scroll"><article className="mdb-reading"><div className="mdb-kicker">{t('agent.memoryView.activity')}</div><h2>{activity.project}</h2><p className="mdb-muted">{format(activity.date)}</p><dl className="mdb-activity-grid">{(['userTurns', 'tasksCreated', 'tasksCompleted', 'tasksFailed'] as const).map((key, index) => <div key={key}><dt>{t('agent.count.' + key)}</dt><dd>{new Intl.NumberFormat(locale).format([activity.turns, activity.created, activity.completed, activity.failed][index])}</dd></div>)}</dl></article></div></> : <div className="mdb-empty"><NotebookIcon size={28} /><p>{t('agent.memoryBrowse.choose')}</p></div>
  const content = <div className={`mdb-browser ${route.id ? 'has-selection' : ''} ${mode === 'rail' ? 'is-rail' : ''}`}>{list}<section className="mdb-detail-pane" aria-label={t('agent.memoryBrowse.detail')}>{detail}</section></div>
  const phoneNav = <nav className="mdb-mobile-nav" aria-label={t('mobile.nav.bottom')}>{[[HomeIcon, 'nav.home'], [FolderIcon, 'nav.projects'], [AppsIcon, 'nav.groupTools'], [GearIcon, 'nav.env']].map(([Icon, key]: any) => <button type="button" key={key} aria-current={key === 'nav.home' ? 'page' : undefined} onClick={() => { if (key === 'nav.home') navigate({ id: '', source: false }) }}><Icon size={22} /><span>{t(key)}</span></button>)}</nav>
  if (phone) return <>{phoneNav}{selected && <Dropdown open={mobileMenu} onOpenChange={setMobileMenu} trigger={['click']} menu={menu}><span className="mdb-mobile-menu-anchor" /></Dropdown>}<MobileSubPage title={route.source ? t('agent.memoryBrowse.sourceConversation') : route.id ? t(activity ? 'agent.memoryBrowse.activityDetail' : 'agent.memoryBrowse.detail') : t('agent.memory')} onBack={back} search={false} manageHistory={false} keepBottomNav action={selected && !route.source ? { label: t('agent.memoryMore', { title: selected.title }), icon: <MoreIcon size={20} />, onClick: () => setMobileMenu(value => !value) } : undefined}>{content}</MobileSubPage></>
  return <div className={`mdb-shell ${mode === 'rail' ? 'with-chat' : ''}`}><aside className="mdb-nav"><strong><AppsIcon size={24} /></strong>{[[HomeIcon, 'nav.home'], [FolderIcon, 'nav.projects'], [AppsIcon, 'nav.groupTools'], [GearIcon, 'nav.env']].map(([Icon, key]: any) => <button type="button" key={key} aria-current={key === 'nav.home' ? 'page' : undefined} aria-label={t(key)} onClick={() => { if (key === 'nav.home') setViewMode('rail') }}><Icon size={20} /><span>{t(key)}</span></button>)}</aside>{mode === 'rail' && <main className="mdb-chat"><header className="tt-pagehead"><h2>Roami</h2><span className="mdb-muted">{t('agent.memoryBrowse.prototype')}</span></header><div className="mdb-chat-history"><p className="mdb-muted">{t('agent.memoryBrowse.prototypeHint')}</p><p className="mdb-bubble">帮我记下，以后分配复杂任务，首选codex</p><div><strong>Roami</strong><p>已记下：以后复杂任务优先交给 Codex。</p></div></div><div className="mdb-composer"><Input.TextArea placeholder={t('agent.placeholder')} autoSize={{ minRows: 2 }} /></div></main>}<main className="mdb-main">{mode === 'rail' ? <header className="mdb-workspace-head"><span>{t('agent.workspace.tasks')}</span><span><BellIcon size={16} />{t('agent.notifications')}</span><strong><NotebookIcon size={16} />{t('agent.memory')}</strong><button type="button" className="mdb-icon tt-act" aria-label={t('agent.memoryBrowse.browse')} onClick={() => setViewMode('library')}><OpenInIcon size={18} /></button></header> : <header className="tt-pagehead"><h2>{t('agent.memory')}</h2><div className="acts"><button type="button" className="tt-act" onClick={() => setViewMode('rail')}><ChevronLeft size={16} />{t('nav.home')}</button></div></header>}{content}</main></div>
}

createRoot(document.getElementById('root')!).render(<I18nProvider><ThemeProvider><App><Prototype /></App></ThemeProvider></I18nProvider>)
