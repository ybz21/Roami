// 手机「项目」页：按项目分组的会话列表。
// 数据只吃一条 GET /sessions/overview（会话 + 归属 + 探测循环的活状态），5s 一轮——
// 桌面树那三条原料手机上不齐（worktree 那趟被省了），拿来画只会全成散会话。
import { useEffect, useMemo, useRef, useState } from 'react'
import { Input, Modal, Spin, App as AntApp } from 'antd'
import { api } from '../../api'
import { pollWhileVisible } from '../../visible-poll'
import { loadSwarmDirectory } from '../swarm/swarm-directory'
import { swarmSessionMembership, type SwarmSessionMember } from '../swarm/swarm-session-membership'
import { useI18n } from '../../i18n'
import { AgentLogo, ChevronRight, CloseIcon, PencilIcon, StopIcon, SwarmIcon, TerminalIcon, PlusIcon } from '../../icons'
import { MobileSheet, SheetRow } from '../shell/MobileSheet'
import SessionLocation from '../sessions/SessionLocation'
import SessionHierarchy from '../sessions/SessionHierarchy'
import { absTime, relTime } from '../../time-format'
import MobileProjectDetail from './MobileProjectDetail'
import { useNativeSessionList, refreshSessionLists } from '../sessions/native-session-list'
import { nativeSessionRecord } from '../sessions/session-record'
import { renameSession, closeSession, stopSession, sessionActionError } from '../sessions/session-actions'
import MobilePageSearch from './MobilePageSearch'
import MobileSubPage from '../MobileSubPage'
import { SessionActivity, SESSION_ACTIVITY_CSS } from '../projects/project-list/session-activity'
import { readMobileOverview, writeMobileOverview, type OverviewItem } from './mobile-overview-cache'
import { readMobileProjects, writeMobileProjects, type MobileProject } from './mobile-project-cache'
import { projectPath } from '../projects/okr/okr-workspace'
import { getHashParams, setHashParams } from '../../route-hash'
import { useSessionOverview } from '../../session-overview'
export type { OverviewItem } from './mobile-overview-cache'

export default function MobileSessions({ onOpen, onNewTask, onNewInWorktree, openProject, searchNonce = 0, initialProjectKey }: {
  initialProjectKey?: string
  onOpen: (name: string) => void
  /** 首页点项目进来：at 每次都变，同一个项目点两次也能再开 */
  openProject?: { name: string; dir: string; at: number } | null
  onNewTask: (dir?: string) => void
  onNewInWorktree: (kind: 'claude' | 'codex' | 'shell', path: string) => void
  searchNonce?: number
}) {
  const { t } = useI18n()
  const overview = useSessionOverview()
  const [items, setItems] = useState<OverviewItem[] | null>(() => readMobileOverview())
  const [, setActivityTick] = useState(0)
  useEffect(() => {
    if (overview.loaded) setItems(writeMobileOverview(overview.value))
    else if (overview.failed) setItems(current => current || [])
  }, [overview.loaded, overview.value, overview.failed])
  useEffect(() => pollWhileVisible(async () => { setActivityTick(tick => tick + 1) }, 30000).stop, [])
  const [projects, setProjects] = useState<MobileProject[] | null>(() => readMobileProjects())
  const native = useNativeSessionList()
  const allItems = useMemo(() => [...(items || []), ...native.value.map(session => {
    const record = nativeSessionRecord(session), project = projects?.find(project => project.key === session.projectId)
    return { ...record, project: project?.name, projectDir: project?.dir }
  })].sort((a, b) => b.lastActivity - a.lastActivity || a.name.localeCompare(b.name)), [items, native.value, projects])
  const loadError = overview.failed
  const [q, setQ] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const searchInput = useRef<HTMLInputElement>(null)
  const lastSearchNonce = useRef(searchNonce)
  useEffect(() => {
    if (searchNonce === lastSearchNonce.current) return
    lastSearchNonce.current = searchNonce
    setFilter('all')
    setSearchOpen(true)
  }, [searchNonce])
  useEffect(() => {
    if (!searchOpen) return
    const frame = requestAnimationFrame(() => searchInput.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [searchOpen, searchNonce])
  // 筛选药丸 + 每组先露 5 条（Lody 手机端的做法）：十几个会话时一屏能看到所有项目，而不是被第一个项目占满
  const [filter, setFilter] = useState<'all' | 'waiting' | 'running' | 'idle' | 'unfinished' | 'activity'>('all')
  useEffect(() => {
    const fromLink = () => {
      const params = getHashParams()
      const target = params.get('filter')
      if (target !== 'waiting' && target !== 'running') return
      setFilter(target)
      params.delete('filter')
      setHashParams(Object.fromEntries(params))
    }
    fromLink()
    window.addEventListener('hashchange', fromLink)
    return () => window.removeEventListener('hashchange', fromLink)
  }, [])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  // 点开的项目（worktree 视图）；安卓返回手势退回列表
  const [cur, setCur] = useState<{ name: string; dir: string } | null>(null)
  const enterProject = (project: { name: string; dir: string }) => {
    const key = projects?.find(p => p.dir === project.dir)?.key
    if (key) { const query = getHashParams().toString(); location.hash = '#/' + projectPath(key) + (query ? '?' + query : '') }
    else setCur(project)
  }
  const handledProject = useRef(0)
  useEffect(() => { if (openProject && projects && handledProject.current !== openProject.at) { handledProject.current = openProject.at; if (!initialProjectKey) enterProject(openProject) } }, [openProject?.at, projects, initialProjectKey]) // eslint-disable-line react-hooks/exhaustive-deps
  // 长按一行：改名 / 中断 / 关闭（24 稿 §5 会话列表）
  const { message, modal } = AntApp.useApp()
  const [menu, setMenu] = useState<OverviewItem | null>(null)
  const lp = useRef<{ timer: number; fired: boolean }>({ timer: 0, fired: false })
  const lpStart = (s: OverviewItem) => { lp.current.fired = false; clearTimeout(lp.current.timer); lp.current.timer = window.setTimeout(() => { lp.current.fired = true; setMenu(s) }, 500) }
  const lpCancel = () => clearTimeout(lp.current.timer)
  const [renaming, setRenaming] = useState<OverviewItem | null>(null)
  const [renameVal, setRenameVal] = useState('')
  const reload = refreshSessionLists
  const interrupt = async (s: OverviewItem) => {
    try { await stopSession(s.name); message.success(t('mobile.interrupted')) }
    catch (e: any) { message.error(sessionActionError(e, t)) }
  }
  const close = (s: OverviewItem) => modal.confirm({
    title: t('session.closeConfirm', { name: s.label }), okText: t('session.close'), okButtonProps: { danger: true }, cancelText: t('common.cancel'),
    onOk: async () => { try { await closeSession(s.name); void reload() } catch (e: any) { message.error(sessionActionError(e, t)) } },
  })
  const rename = async () => {
    const s = renaming, name = renameVal.trim()
    if (!s || !name || name === s.label) return
    try { await renameSession(s.name, name); setRenaming(null); void reload() } catch (e: any) { message.error(sessionActionError(e, t)) }
  }
  useEffect(() => {
    let stop = false
    const load = () => api('GET', '/projects').then((r) => { if (!stop) setProjects(writeMobileProjects(r.data.projects || [])) }).catch(() => {})
    load()
    const timer = setInterval(load, 20000)
    return () => { stop = true; clearInterval(timer) }
  }, [])

  const [swarmOf, setSwarmOf] = useState<Record<string, SwarmSessionMember>>({})
  const [swarmPending, setSwarmPending] = useState<Record<string, number>>({})
  useEffect(() => pollWhileVisible(async signal => {
    const groups = await loadSwarmDirectory()
    if (!signal.aborted) {
      const membership = swarmSessionMembership(groups)
      setSwarmOf(membership.sessions); setSwarmPending(membership.pending)
    }
  }, 10000).stop, [])

  const needle = q.trim().toLowerCase()
  const inFilter = (s: OverviewItem) => filter === 'all' || (filter === 'waiting' ? s.waiting : filter === 'running' ? s.running : filter === 'activity' || filter === 'unfinished' ? false : !s.waiting && !s.running && !s.dormant)
  const hit = (s: OverviewItem) => inFilter(s) && (!needle || [s.label, s.name, s.branch, s.worktree, s.cwd].some(value => value?.toLowerCase().includes(needle)))
  const groups = useMemo(() => {
    const by = new Map<string, { name: string; dir: string; list: OverviewItem[] }>()
    for (const s of allItems) {
      if (!hit(s)) continue
      const k = s.projectKey || ''
      if (!by.has(k)) by.set(k, { name: s.project || t('tree.loose'), dir: s.projectDir || '', list: [] })
      by.get(k)!.list.push(s)
    }
    // 散会话垫底
    return Array.from(by.entries()).sort((a, b) => (a[0] === '' ? 1 : 0) - (b[0] === '' ? 1 : 0)).map(([, g]) => g)
  }, [allItems, needle, filter]) // eslint-disable-line react-hooks/exhaustive-deps
  const unfinishedByDir = new Map((projects || []).map((p) => [p.dir, p.unfinished]))
  const unfinishedProjects = (projects || []).filter((p) => p.unfinished > 0 && (!needle || p.name.toLowerCase().includes(needle)))
  const visibleGroups = filter === 'all' ? [
    ...groups,
    ...unfinishedProjects.filter(project => !groups.some(group => group.dir === project.dir)).map(project => ({ name: project.name, dir: project.dir, list: [] as OverviewItem[] })),
  ] : groups

  const status = (s: OverviewItem) => s.dormant ? t('mobile.st.dormant') : s.waiting ? t('mobile.st.waiting') : s.running ? t('mobile.st.running') : t('mobile.st.idle')
  const row = (s: OverviewItem, sub = false) => (
    <button key={s.name} type="button" className={`tt-msess-row${sub ? ' sub' : ''}${s.waiting ? ' wait' : ''}${s.dormant ? ' dormant' : ''}`}
      onClick={() => { if (lp.current.fired) { lp.current.fired = false; return } onOpen(s.name) }}
      onTouchStart={() => lpStart(s)} onTouchMove={lpCancel} onTouchEnd={lpCancel} onTouchCancel={lpCancel}
      onContextMenu={(e) => { e.preventDefault(); setMenu(s) }}>
      <span className="ic">{s.agent ? <AgentLogo kind={s.agent} size={16} /> : <TerminalIcon size={16} />}</span>
      <span className="t">
        <b>{s.label}</b>
        <span className="st"><i>{status(s)}</i>{(s.waiting || s.running) && s.tail ? <span className="tail"> · {s.tail}</span> : null}</span>
        <SessionLocation {...s} />
      </span>
      <em title={absTime(s.lastActivity)}>{relTime(s.lastActivity, t)}</em>
    </button>
  )

  // 一个分组里：蜂群成员按蜂群折成卡（首次出现的位置），其余照常一行一个
  const swarmCards = (list: OverviewItem[], limit?: number) => {
    const seen = new Set<string>()
    return <SessionHierarchy sessions={list} allSessions={allItems} limit={limit} renderRow={s => {
      const sw = swarmOf[s.name]
      if (!sw) return row(s)
      if (seen.has(sw.swarm)) return null
      seen.add(sw.swarm)
      const members = list.filter((x) => swarmOf[x.name]?.swarm === sw.swarm)
      const pending = swarmPending[sw.swarm] || 0
      return (
        <div key={'sw:' + sw.swarm} className="tt-msess-task swarm">
          <button type="button" className="tn" onClick={() => { location.hash = '#/swarm/' + encodeURIComponent(sw.swarm) }}>
            <SwarmIcon size={14} /><b>{sw.label}</b><span>{members.length}</span>
            {pending > 0 && <i className="pend">{t('swarm.pendingSummary', { count: pending })}</i>}
            <ChevronRight size={14} />
          </button>
          <SessionHierarchy sessions={members} allSessions={allItems} renderRow={x => row(x, true)} />
        </div>
      )
    }} />
  }

  if (initialProjectKey) {
    const project = projects?.find(project => project.key === initialProjectKey)
    return <MobileSubPage title={project?.name || t('nav.projects')} manageHistory={false} onBack={() => { const query = getHashParams().toString(); location.hash = '#/projects' + (query ? '?' + query : '') }} keepBottomNav>
      {project ? <MobileProjectDetail projectId={project.key} dir={project.dir} onOpenSession={onOpen} onNewInWorktree={onNewInWorktree} /> : <p role="status">{projects === null ? t('common.loading') : t('agent.activity.detailsUnavailable')}</p>}
    </MobileSubPage>
  }
  if (items === null) return <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}><Spin /></div>
  if (cur) return <MobileSubPage title={cur.name} onBack={() => setCur(null)} keepBottomNav
    action={{ label: t('mobile.proj.newTask'), icon: <PlusIcon size={20} />, onClick: () => onNewTask(cur.dir) }}>
    <MobileProjectDetail projectId={projects?.find(project => project.dir === cur.dir)?.key} dir={cur.dir} onOpenSession={onOpen} onNewInWorktree={onNewInWorktree} />
  </MobileSubPage>
  return (
    <div className="tt-msess">
      <style>{SESSION_ACTIVITY_CSS}</style>
      {(loadError || native.failed) && <div className="tt-data-error" role="alert">{t('mobile.overviewLoadFailed')} <button type="button" className="tt-act" onClick={reload}>{t('inbox.retry')}</button></div>}
      <header className="tt-pagehead tt-mobile-pagehead">
        <div className="ttl">
          <div className="kicker">{t('mobile.sessions.kicker')}</div>
          <h2>{t('nav.projects')}</h2>
          <p>{t('mobile.sessions.lead')}</p>
        </div>
        <div className="acts">
          <button type="button" className="tt-mobile-action" onClick={() => onNewTask()}><PlusIcon size={16} />{t('mobile.newSession')}</button>
        </div>
      </header>
      {(searchOpen || q) && <div className="tt-msess-head">
        <MobilePageSearch inputRef={searchInput} value={q} onChange={setQ} placeholder={t('mobile.searchSessions')}
          onDismiss={() => { setQ(''); setSearchOpen(false) }} />
      </div>}
      <div className="tt-msess-pills">
        {(['all', 'waiting', 'running', 'idle', 'unfinished', 'activity'] as const).map((k) => {
          const n = k === 'activity' ? null : k === 'unfinished' ? projects?.reduce((sum, p) => sum + p.unfinished, 0) ?? null : k === 'all' ? allItems.length : allItems.filter((x) => (k === 'waiting' ? x.waiting : k === 'running' ? x.running : !x.waiting && !x.running && !x.dormant)).length
          return <button key={k} type="button" className={`tt-pill${filter === k ? ' on' : ''}`} aria-pressed={filter === k} onClick={() => { setFilter(k); if (k === 'activity') { setQ(''); setSearchOpen(false) } }}>{t(k === 'all' ? 'mobile.filter.all' : k === 'unfinished' ? 'mobile.home.unfinished' : k === 'activity' ? 'project.sessionActivity' : 'mobile.st.' + k)}{n !== null && n > 0 && <span>{n}</span>}</button>
        })}
      </div>
      {filter === 'activity' ? <SessionActivity onOpenSession={onOpen} showEmpty /> : filter === 'unfinished' ? (
        projects === null ? <div className="tt-msess-empty" role="status">{t('common.loading')}</div>
          : unfinishedProjects.length ? unfinishedProjects.map((p) => (
            <button key={p.key} type="button" className="tt-msess-unfinished" onClick={() => enterProject(p)}>
              <span className="av">{p.name.slice(0, 1).toUpperCase()}</span><span className="name">{p.name}</span>
              <span className="count">{t('mobile.proj.unfinished', { n: p.unfinished })}</span><ChevronRight size={14} />
            </button>
          )) : <div className="tt-msess-empty">{t('tree.noTasks')}</div>
      ) : visibleGroups.map((g, i) => (
        <section key={i} className="tt-msess-sec">
          {g.dir
            ? <button type="button" className="tt-msess-proj" onClick={() => enterProject(g)}><h3>{g.name} {g.list.length > 0 && <span>{g.list.length}</span>}</h3>{(unfinishedByDir.get(g.dir) || 0) > 0 && <span className="unfinished">{t('mobile.proj.unfinished', { n: unfinishedByDir.get(g.dir) || 0 })}</span>}<ChevronRight size={14} /></button>
            : <h3>{g.name} <span>{g.list.length}</span></h3>}
          {swarmCards(g.list, needle || filter !== 'all' || expanded.has(g.name) ? undefined : 5)}
          {!needle && filter === 'all' && g.list.length > 5 && (
            <button type="button" className="tt-mproj-more" onClick={() => setExpanded((cur) => { const n = new Set(cur); if (n.has(g.name)) n.delete(g.name); else n.add(g.name); return n })}>
              {expanded.has(g.name) ? t('mobile.proj.hideQuiet') : t('mobile.moreN', { n: g.list.length - 5 })}
            </button>
          )}
        </section>
      ))}
      {filter !== 'activity' && filter !== 'unfinished' && !visibleGroups.length && <div className="tt-msess-empty">{t('tree.noTasks')}</div>}
      <MobileSheet open={!!menu} title={menu?.label || ''} onClose={() => setMenu(null)}>
        {menu && <>
          <SheetRow icon={<PencilIcon size={16} />} title={t('session.rename')} onClick={() => { setRenameVal(menu.label); setRenaming(menu); setMenu(null) }} />
          {(menu.running || menu.waiting) && <SheetRow icon={<StopIcon size={16} />} title={t('mobile.interrupt')} desc={t('mobile.interruptHelp')} onClick={() => { void interrupt(menu); setMenu(null) }} />}
          <SheetRow icon={<CloseIcon size={16} />} title={t('session.close')} danger onClick={() => { const m = menu; setMenu(null); close(m) }} />
        </>}
      </MobileSheet>
      <Modal open={!!renaming} title={t('session.rename')} okText={t('common.confirm')} cancelText={t('common.cancel')} onOk={rename} onCancel={() => setRenaming(null)} destroyOnClose>
        <Input autoFocus value={renameVal} onChange={(e) => setRenameVal(e.target.value)} onPressEnter={rename} />
      </Modal>
    </div>
  )
}
