// 手机「项目」页：按项目分组的会话列表。
// 数据只吃一条 GET /sessions/overview（会话 + 归属 + 探测循环的活状态），5s 一轮——
// 桌面树那三条原料手机上不齐（worktree 那趟被省了），拿来画只会全成散会话。
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Input, Modal, Spin, App as AntApp } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { AgentLogo, ChevronRight, CloseIcon, PencilIcon, StopIcon, SwarmIcon, TerminalIcon, PlusIcon } from '../../icons'
import { MobileSheet, SheetRow } from '../shell/MobileSheet'
import { BranchIcon } from '../git/parts'
import MobileProjectDetail from './MobileProjectDetail'
import MobilePageSearch from './MobilePageSearch'
import MobileSubPage from '../MobileSubPage'
import { SessionActivity, SESSION_ACTIVITY_CSS } from '../projects/project-list/session-activity'
import { readMobileOverview, writeMobileOverview, type OverviewItem } from './mobile-overview-cache'
export type { OverviewItem } from './mobile-overview-cache'

function ago(sec: number | undefined, t: (k: string) => string): string {
  if (!sec) return ''
  const d = Math.max(0, Math.floor(Date.now() / 1000 - sec))
  if (d < 60) return t('time.justNow')
  if (d < 3600) return `${Math.floor(d / 60)}m`
  if (d < 86400) return `${Math.floor(d / 3600)}h`
  return `${Math.floor(d / 86400)}d`
}

export default function MobileSessions({ onOpen, onNewTask, onNewInWorktree, openProject, searchNonce = 0 }: {
  onOpen: (name: string) => void
  /** 首页点项目进来：at 每次都变，同一个项目点两次也能再开 */
  openProject?: { name: string; dir: string; at: number } | null
  onNewTask: (dir?: string) => void
  onNewInWorktree: (kind: 'claude' | 'codex' | 'shell', path: string) => void
  searchNonce?: number
}) {
  const { t } = useI18n()
  const [items, setItems] = useState<OverviewItem[] | null>(() => readMobileOverview())
  const [loadError, setLoadError] = useState(false)
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
  const [filter, setFilter] = useState<'all' | 'waiting' | 'running' | 'idle' | 'activity'>('all')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  // 点开的项目（worktree 视图）；安卓返回手势退回列表
  const [cur, setCur] = useState<{ name: string; dir: string } | null>(null)
  useEffect(() => { if (openProject) setCur({ name: openProject.name, dir: openProject.dir }) }, [openProject?.at]) // eslint-disable-line react-hooks/exhaustive-deps
  // 长按一行：改名 / 中断 / 关闭（24 稿 §5 会话列表）
  const { message, modal } = AntApp.useApp()
  const [menu, setMenu] = useState<OverviewItem | null>(null)
  const lp = useRef<{ timer: number; fired: boolean }>({ timer: 0, fired: false })
  const lpStart = (s: OverviewItem) => { lp.current.fired = false; clearTimeout(lp.current.timer); lp.current.timer = window.setTimeout(() => { lp.current.fired = true; setMenu(s) }, 500) }
  const lpCancel = () => clearTimeout(lp.current.timer)
  const [renaming, setRenaming] = useState<OverviewItem | null>(null)
  const [renameVal, setRenameVal] = useState('')
  const reload = () => api('GET', '/sessions/overview').then((r) => { setItems(writeMobileOverview(r.data.items || [])); setLoadError(false) }).catch(() => { setLoadError(true); setItems((cur) => cur || []) })
  const interrupt = async (s: OverviewItem) => {
    try { await api('POST', `/sessions/${encodeURIComponent(s.name)}/keys`, { keys: ['Escape'] }); message.success(t('mobile.interrupted')) }
    catch (e: any) { message.error(e.message) }
  }
  const close = (s: OverviewItem) => modal.confirm({
    title: t('session.closeConfirm', { name: s.label }), okText: t('session.close'), okButtonProps: { danger: true }, cancelText: t('common.cancel'),
    onOk: async () => { try { await api('DELETE', `/sessions/${encodeURIComponent(s.name)}`); void reload() } catch (e: any) { message.error(e.message) } },
  })
  const rename = async () => {
    const s = renaming, name = renameVal.trim()
    setRenaming(null)
    if (!s || !name || name === s.label) return
    try { await api('PATCH', `/sessions/${encodeURIComponent(s.name)}`, { name }); void reload() } catch (e: any) { message.error(e.message) }
  }
  useEffect(() => {
    let stop = false
    const load = () => api('GET', '/sessions/overview').then((r) => { if (!stop) { setItems(writeMobileOverview(r.data.items || [])); setLoadError(false) } }).catch(() => { if (!stop) { setLoadError(true); setItems((c) => c || []) } })
    load()
    const i = setInterval(load, 5000)
    return () => { stop = true; clearInterval(i) }
  }, [])

  // 蜂群：成员会话折成一张卡（领队一行、成员缩进、N 待解锁），点卡头进蜂群页。和桌面会话页同一条取数路
  const [swarmOf, setSwarmOf] = useState<Record<string, { swarm: string; role: 'leader' | 'member' }>>({})
  const [swarmPending, setSwarmPending] = useState<Record<string, number>>({})
  useEffect(() => {
    let stop = false
    const load = async () => {
      try {
        const swarms = await api('GET', '/swarms')
        if (!Array.isArray(swarms)) return
        const of: typeof swarmOf = {}, pend: Record<string, number> = {}
        await Promise.all(swarms.map(async (sw: any) => {
          try {
            const st = await api('GET', `/swarms/${encodeURIComponent(sw.name)}`)
            if (st?.supervisor) of[st.supervisor] = { swarm: sw.name, role: 'leader' }
            for (const m of (st?.members || [])) if (m?.session) of[m.session] = { swarm: sw.name, role: m.role === 'leader' || m.role === 'master' ? 'leader' : 'member' }
            pend[sw.name] = Array.isArray(st?.pending) ? st.pending.length : 0
          } catch {}
        }))
        if (!stop) { setSwarmOf(of); setSwarmPending(pend) }
      } catch {}
    }
    void load()
    const i = setInterval(load, 10000)
    return () => { stop = true; clearInterval(i) }
  }, [])

  const needle = q.trim().toLowerCase()
  const inFilter = (s: OverviewItem) => filter === 'all' || (filter === 'waiting' ? s.waiting : filter === 'running' ? s.running : filter === 'activity' ? false : !s.waiting && !s.running && !s.dormant)
  const hit = (s: OverviewItem) => inFilter(s) && (!needle || s.label.toLowerCase().includes(needle) || s.name.toLowerCase().includes(needle) || (s.branch || '').toLowerCase().includes(needle))
  const groups = useMemo(() => {
    const by = new Map<string, { name: string; dir: string; list: OverviewItem[] }>()
    for (const s of items || []) {
      if (!hit(s)) continue
      const k = s.projectKey || ''
      if (!by.has(k)) by.set(k, { name: s.project || t('tree.loose'), dir: s.projectDir || '', list: [] })
      by.get(k)!.list.push(s)
    }
    // 散会话垫底
    return Array.from(by.entries()).sort((a, b) => (a[0] === '' ? 1 : 0) - (b[0] === '' ? 1 : 0)).map(([, g]) => g)
  }, [items, needle, filter]) // eslint-disable-line react-hooks/exhaustive-deps

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
        {s.branch && <span className="br"><BranchIcon size={11} />{s.branch}</span>}
      </span>
      <em>{ago(s.lastActivity, t)}</em>
    </button>
  )

  // 一个分组里：蜂群成员按蜂群折成卡（首次出现的位置），其余照常一行一个
  const swarmCards = (list: OverviewItem[]) => {
    const out: ReactNode[] = []
    const seen = new Set<string>()
    for (const s of list) {
      const sw = swarmOf[s.name]
      if (!sw) { out.push(row(s)); continue }
      if (seen.has(sw.swarm)) continue
      seen.add(sw.swarm)
      const members = list.filter((x) => swarmOf[x.name]?.swarm === sw.swarm)
      const leader = members.filter((x) => swarmOf[x.name]?.role === 'leader'), rest = members.filter((x) => swarmOf[x.name]?.role !== 'leader')
      const pending = swarmPending[sw.swarm] || 0
      out.push(
        <div key={'sw:' + sw.swarm} className="tt-msess-task swarm">
          <button type="button" className="tn" onClick={() => { location.hash = '#/swarm/' + encodeURIComponent(sw.swarm) }}>
            <SwarmIcon size={14} /><b>{sw.swarm}</b><span>{members.length}</span>
            {pending > 0 && <i className="pend">{t('swarm.pendingSummary', { count: pending })}</i>}
            <ChevronRight size={14} />
          </button>
          {[...leader, ...rest].map((x) => row(x, true))}
        </div>,
      )
    }
    return out
  }

  if (items === null) return <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}><Spin /></div>
  if (cur) return <MobileSubPage title={cur.name} onBack={() => setCur(null)}
    action={{ label: t('mobile.proj.newTask'), icon: <PlusIcon size={20} />, onClick: () => onNewTask(cur.dir) }}>
    <MobileProjectDetail dir={cur.dir} onOpenSession={onOpen} onNewInWorktree={onNewInWorktree} />
  </MobileSubPage>
  return (
    <div className="tt-msess">
      <style>{SESSION_ACTIVITY_CSS}</style>
      {loadError && <div className="tt-data-error" role="alert">{t('mobile.overviewLoadFailed')} <button type="button" className="tt-act" onClick={() => void reload()}>{t('inbox.retry')}</button></div>}
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
        {(['all', 'waiting', 'running', 'idle', 'activity'] as const).map((k) => {
          const n = k === 'activity' ? null : k === 'all' ? items.length : items.filter((x) => (k === 'waiting' ? x.waiting : k === 'running' ? x.running : !x.waiting && !x.running && !x.dormant)).length
          return <button key={k} type="button" className={`tt-pill${filter === k ? ' on' : ''}`} aria-pressed={filter === k} onClick={() => { setFilter(k); if (k === 'activity') { setQ(''); setSearchOpen(false) } }}>{t(k === 'all' ? 'mobile.filter.all' : k === 'activity' ? 'project.sessionActivity' : 'mobile.st.' + k)}{n !== null && <span>{n}</span>}</button>
        })}
      </div>
      {filter === 'activity' ? <SessionActivity onOpenSession={onOpen} showEmpty /> : groups.map((g, i) => (
        <section key={i} className="tt-msess-sec">
          {g.dir
            ? <button type="button" className="tt-msess-proj" onClick={() => setCur({ name: g.name, dir: g.dir })}><h3>{g.name} <span>{g.list.length}</span></h3><ChevronRight size={14} /></button>
            : <h3>{g.name} <span>{g.list.length}</span></h3>}
          {swarmCards(needle || filter !== 'all' || expanded.has(g.name) ? g.list : g.list.slice(0, 5))}
          {!needle && filter === 'all' && g.list.length > 5 && (
            <button type="button" className="tt-mproj-more" onClick={() => setExpanded((cur) => { const n = new Set(cur); if (n.has(g.name)) n.delete(g.name); else n.add(g.name); return n })}>
              {expanded.has(g.name) ? t('mobile.proj.hideQuiet') : t('mobile.moreN', { n: g.list.length - 5 })}
            </button>
          )}
        </section>
      ))}
      {filter !== 'activity' && !items.length && <div className="tt-msess-empty">{t('tree.noTasks')}</div>}
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
