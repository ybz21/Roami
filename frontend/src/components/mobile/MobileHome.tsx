// 手机首页只给状态摘要；会话提醒与项目收尾都在项目页处理。
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { AgentLogo, ChevronRight, TerminalIcon } from '../../icons'
import { BranchIcon } from '../git/parts'
import { readMobileOverview, writeMobileOverview, type OverviewItem } from './mobile-overview-cache'
import { AppUpdateBanner } from './app-update'

const HOST_MONITOR = 'roam.host-monitor'
type Inbox = { id: number; type: string; session: string; label: string; body: string; at: number; read: boolean }
type Host = { hostname: string; cpu: number; temp: number; mem: number; memFree: number; swap: number; disk: number; load: number; cores: number }
type Item = OverviewItem & { yesNo?: boolean }

function ago(sec: number, t: (k: string) => string): string {
  const d = Math.max(0, Math.floor(Date.now() / 1000 - sec))
  if (d < 60) return t('time.justNow')
  if (d < 3600) return `${Math.floor(d / 60)}m`
  if (d < 86400) return `${Math.floor(d / 3600)}h`
  return `${Math.floor(d / 86400)}d`
}

type Proj = { key: string; name: string; dir: string; sessions: number; unfinished: number; worktrees: number; lastActivity: number }

export default function MobileHome({ last, onOpen, onNav, onOpenProject }: {
  /** 上次看的会话，给「继续上次」用 */
  last: string | null
  onOpen: (name: string) => void
  onNav: (key: string) => void
  onOpenProject: (p: { name: string; dir: string }) => void
}) {
  const { t } = useI18n()
  const [items, setItems] = useState<Item[] | null>(() => readMobileOverview())
  const [inbox, setInbox] = useState<Inbox[]>([])
  const [projects, setProjects] = useState<Proj[]>([])
  const [host, setHost] = useState<Host | null>(null)
  const [hostStatus, setHostStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const [overviewError, setOverviewError] = useState(false)

  const loadLive = useCallback(() => api('GET', '/sessions/overview').then((r) => { setItems(writeMobileOverview(r.data.items || [])); setOverviewError(false) }).catch(() => { setOverviewError(true); setItems((c) => c || []) }), [])
  useEffect(() => {
    let stop = false
    const slow = () => {
      api('GET', '/inbox?limit=40').then((r) => { if (!stop) setInbox(r.data.items || []) }).catch(() => {})
      api('GET', '/projects').then((r) => { if (!stop) setProjects(r.data.projects || []) }).catch(() => {})
      api('POST', `/plugins/${encodeURIComponent(HOST_MONITOR)}/run`, { command: 'host-monitor.stats', args: {} }).then((d) => {
        if (stop) return
        if (!d?.memory) { setHostStatus((s) => s === 'ready' ? s : 'unavailable'); return }
        const root = (d.disks || []).find((x: any) => x.mount === '/') || (d.disks || [])[0]
        setHost({
          hostname: d.host?.hostname || '', cpu: d.cpu?.usagePercent || 0, temp: d.cpu?.tempC || 0, cores: d.cpu?.cores || 1, load: d.host?.load1 || 0,
          mem: d.memory.usagePercent || 0, memFree: d.memory.available || 0,
          swap: d.memory.swapTotal ? (d.memory.swapUsed / d.memory.swapTotal) * 100 : 0, disk: root?.usagePercent || 0,
        })
        setHostStatus('ready')
      }).catch(() => { if (!stop) setHostStatus((s) => s === 'ready' ? s : 'unavailable') })
    }
    void loadLive(); slow()
    const a = setInterval(loadLive, 5000), b = setInterval(slow, 20000)
    return () => { stop = true; clearInterval(a); clearInterval(b) }
  }, [loadLive])

  if (items === null) return <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}><Spin /></div>

  const waiting = items.filter((s) => s.waiting)
  const running = items.filter((s) => s.running)
  const dayStart = new Date().setHours(0, 0, 0, 0) / 1000
  const doneToday = inbox.filter((x) => x.type === 'session.done' && x.at >= dayStart)
  const errors = inbox.filter((x) => x.type === 'session.error' && !x.read)

  const unfinished = projects.reduce((n, p) => n + p.unfinished, 0)
  const needs = waiting.length + errors.length
  // 和电脑版主页同一句话：先问候，再说今天有几件事要你
  const h = new Date().getHours()
  const greet = t(h < 12 ? 'overview.greetMorning' : h < 18 ? 'overview.greetAfternoon' : 'overview.greetEvening')
  const headline = greet + (needs ? t('mobile.home.headNeeds', { n: needs })
    : running.length ? t('mobile.home.headRunning', { n: running.length }) : t('mobile.home.headQuiet'))
  const lastItem = last ? items.find((x) => x.name === last && !x.waiting) : undefined
  const busyProjects = [...projects].filter((p) => p.sessions > 0).sort((a, b) => b.lastActivity - a.lastActivity)
  // /projects 的 running 是 Agent 进程数；首页与会话筛选用的是当前忙碌状态。
  const projectActivity = new Map<string, { running: number; waiting: number }>()
  for (const s of items) {
    if (!s.projectKey) continue
    const activity = projectActivity.get(s.projectKey) || { running: 0, waiting: 0 }
    if (s.running) activity.running++
    if (s.waiting) activity.waiting++
    projectActivity.set(s.projectKey, activity)
  }

  const tile = (n: number, label: string, tone: '' | 'warn' | 'ok', to: string) => (
    <button type="button" className={`tile ${n > 0 ? tone : ''}`} onClick={() => onNav(to)}>
      <b>{n}</b><span>{label}</span>
    </button>
  )
  // 资源条：数字用正文色，颜色只给条本身；超线时旁边补一个词，不靠颜色单独表意
  const meter = (label: string, pct: number, extra: string) => {
    const tone = pct >= 90 ? 'danger' : pct >= 75 ? 'warn' : ''
    return (
      <div className="meter">
        <div className="ml"><span>{label}</span><em>{extra}{tone ? ` · ${t(tone === 'danger' ? 'mobile.home.critical' : 'mobile.home.high')}` : ''}</em></div>
        <div className="bar" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}><i className={tone} style={{ width: `${Math.min(100, Math.max(2, pct))}%` }} /></div>
      </div>
    )
  }
  const icon = (s: { agent?: string }) => (s.agent === 'claude' || s.agent === 'codex' ? <AgentLogo kind={s.agent} size={16} /> : <TerminalIcon size={16} />)
  const section = (title: string, n: number | null, more: (() => void) | null, children: ReactNode) => (
    <section className="sec">
      <h3>{title}{n !== null && <span>{n}</span>}{more && <button type="button" onClick={more}>{t('mobile.home.all')}<ChevronRight size={12} /></button>}</h3>
      {children}
    </section>
  )

  return (
    <div className="tt-mhome">
      <AppUpdateBanner />
      {overviewError && <div className="tt-data-error" role="alert">{t('mobile.overviewLoadFailed')} <button type="button" className="tt-act" onClick={() => void loadLive()}>{t('inbox.retry')}</button></div>}
      <header className="tt-pagehead tt-mobile-pagehead">
        <div className="ttl">
          <div className="kicker">{new Date().toLocaleDateString(undefined, { month: 'long', day: 'numeric', weekday: 'long' })}{host?.hostname ? ` · ${host.hostname}` : ''}</div>
          <h2>{headline}</h2>
          <p>{t('mobile.home.lead')}</p>
        </div>
      </header>

      <div className="tiles">
        {tile(waiting.length, t('mobile.st.waiting'), 'warn', 'projects')}
        {tile(running.length, t('mobile.st.running'), 'ok', 'projects')}
        {tile(doneToday.length, t('mobile.home.doneToday'), '', 'projects')}
        {tile(unfinished, t('mobile.home.unfinished'), '', 'projects')}
      </div>

      {needs > 0 && <button type="button" className="inbox-link" onClick={() => onNav('projects')}>
        <span>{t('mobile.home.projectNeeds', { n: needs })}</span><ChevronRight size={16} />
      </button>}

      {lastItem && (
        <button type="button" className="resume" onClick={() => onOpen(lastItem.name)}>
          <span className="ic">{icon(lastItem)}</span>
          <span className="t"><small>{t('mobile.home.resume')}</small><b>{lastItem.label}</b></span>
          <ChevronRight size={16} />
        </button>
      )}

      {section(t('mobile.home.running'), running.length, () => onNav('projects'), running.length ? running.slice(0, 3).map((s) => (
        <button key={s.name} type="button" className="tt-msess-row" onClick={() => onOpen(s.name)}>
          <span className="ic">{icon(s)}</span>
          <span className="t">
            <b>{s.label}</b>
            <span className="st"><span className="tail">{s.tail || t('mobile.st.running')}</span></span>
            {s.branch && <span className="br"><BranchIcon size={11} />{s.branch}</span>}
          </span>
          <em>{ago(s.lastActivity, t)}</em>
        </button>
      )) : <div className="none">{t('mobile.home.noneRunning')}</div>)}

      {busyProjects.length > 0 && section(t('nav.projects'), busyProjects.length, () => onNav('projects'), (
        <div className="projs">
          {busyProjects.slice(0, 4).map((p) => {
            const activity = projectActivity.get(p.key)
            return <button key={p.key} type="button" onClick={() => onOpenProject(p)}>
              <span className="av">{p.name.slice(0, 1).toUpperCase()}</span>
              <span className="t">
                <b>{p.name}</b>
                <small>{t('mobile.home.projMeta', { s: p.sessions, w: p.worktrees })}</small>
              </span>
              {(activity?.waiting || activity?.running) ? <span className="cnt">
                {!!activity?.waiting && <i className="w">{t('mobile.proj.waiting', { n: activity.waiting })}</i>}
                {!!activity?.running && <i className="r">{t('mobile.proj.running', { n: activity.running })}</i>}
              </span> : null}
            </button>
          })}
        </div>
      ))}

      {section(t('mobile.home.machine'), null, null, host ? (
        <div className="host">
          {meter(t('mobile.home.mem'), host.mem, t('mobile.home.memFree', { gb: (host.memFree / 1073741824).toFixed(1) }))}
          {meter(t('mobile.home.swap'), host.swap, `${Math.round(host.swap)}%`)}
          {meter('CPU', host.cpu, `${Math.round(host.cpu)}% · ${t('mobile.home.load', { n: host.load.toFixed(1), cores: host.cores })}${host.temp ? ` · ${Math.round(host.temp)}°C` : ''}`)}
          {meter(t('mobile.home.disk'), host.disk, `${Math.round(host.disk)}%`)}
        </div>
      ) : <div className="host-empty" role="status">{t(hostStatus === 'loading' ? 'mobile.home.machineLoading' : 'mobile.home.machineUnavailable')}</div>)}

    </div>
  )
}
