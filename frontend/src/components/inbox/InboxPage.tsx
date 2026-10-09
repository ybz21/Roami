// 会话通知记录：需要你 / 刚做完 / 出错了。
// 数据来自 GET /inbox（后端从台账 plugin_notifications 里筛 source=roam.web）。
import { useEffect, useState } from 'react'
import { App as AntApp, Button, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { setBadge } from '../../push'
import { CheckIcon, CloseIcon, QuestionIcon } from '../../icons'
import { ICONS } from '../nav-icons'
import { useLayout } from '../../layout'

export type InboxItem = { id: number; type: string; session: string; label: string; body: string; at: number; read: boolean }

function ago(sec: number, t: (k: string, p?: any) => string): string {
  const d = Math.max(0, Math.floor(Date.now() / 1000 - sec))
  if (d < 60) return t('time.justNow')
  if (d < 3600) return `${Math.floor(d / 60)}m`
  if (d < 86400) return `${Math.floor(d / 3600)}h`
  return `${Math.floor(d / 86400)}d`
}

export default function InboxPage({ onOpenSession }: { onOpenSession: (name: string) => void }) {
  const { t } = useI18n()
  const { phone: isMobile } = useLayout()
  const { message } = AntApp.useApp()
  const [items, setItems] = useState<InboxItem[] | null>(null)
  const [filter, setFilter] = useState<'all' | 'waiting' | 'done' | 'error' | 'unread'>('all')
  const [approvable, setApprovable] = useState<Set<string>>(new Set())
  const [acting, setActing] = useState(0)
  const [loadError, setLoadError] = useState(false)

  const load = async () => {
    try {
      const [r, overview] = await Promise.allSettled([api('GET', '/inbox?limit=100'), api('GET', '/sessions/overview')])
      if (r.status === 'rejected') throw r.reason
      const sessions: { name: string; waiting: boolean; yesNo?: boolean }[] = overview.status === 'fulfilled' ? overview.value.data.items || [] : []
      const active = new Set(sessions.filter((s) => s.waiting).map((s) => s.name))
      setApprovable(new Set(sessions.filter((s) => s.waiting && s.yesNo).map((s) => s.name)))
      const next: InboxItem[] = (r.value.data.items || []).filter((it: InboxItem) => it.type !== 'session.waiting' || overview.status === 'rejected' || active.has(it.session))
      setItems(next)
      setBadge(next.filter((it) => it.type === 'session.waiting' && !it.read).length)
      setLoadError(false)
    } catch { setLoadError(true); setItems((cur) => cur || []) }
  }
  useEffect(() => {
    void load()
    const i = setInterval(load, 10000)
    return () => clearInterval(i)
  }, [])
  const markRead = async (ids: number[] | 'all') => {
    setItems((cur) => (cur || []).map((it) => (ids === 'all' || ids.includes(it.id) ? { ...it, read: true } : it)))
    setBadge((items || []).filter((it) => it.type === 'session.waiting' && !it.read && ids !== 'all' && !ids.includes(it.id)).length)
    try { await api('POST', '/inbox/read', ids === 'all' ? { all: true } : { ids }) } catch { /* 下轮刷新会对齐 */ }
  }
  const open = (it: InboxItem) => { if (!it.read) void markRead([it.id]); onOpenSession(it.session) }
  const answer = async (it: InboxItem, key: 'Enter' | 'Escape') => {
    setActing(it.id)
    try {
      await api('POST', `/sessions/${encodeURIComponent(it.session)}/keys`, { keys: [key] })
      await markRead([it.id])
      setApprovable((cur) => { const next = new Set(cur); next.delete(it.session); return next })
      message.success(t(key === 'Enter' ? 'mobile.home.allowed' : 'mobile.home.denied', { name: it.label || it.session }))
      setTimeout(() => void load(), 1500)
    } catch (e: any) { message.error(e.message) } finally { setActing(0) }
  }

  if (items === null) return <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}><Spin /></div>
  const visible = !isMobile || filter === 'all' ? items : items.filter((x) => filter === 'unread' ? !x.read : x.type === `session.${filter}`)
  const waiting = visible.filter((x) => x.type === 'session.waiting')
  const done = visible.filter((x) => x.type === 'session.done')
  const errors = visible.filter((x) => x.type === 'session.error')
  const unread = items.some((x) => !x.read)

  const row = (it: InboxItem) => (
    <div key={it.id} className="tt-inbox-entry">
      <button type="button" className={`tt-inbox-row${it.read ? '' : ' unread'} ${it.type.split('.')[1]}`} onClick={() => open(it)}>
        <span className="ic">{it.type === 'session.waiting' ? <QuestionIcon size={18} /> : it.type === 'session.error' ? <CloseIcon size={18} /> : <CheckIcon size={18} />}</span>
        <span className="t"><b>{it.label || it.session}</b><span>{it.body || t('inbox.noSummary')}</span></span>
        <em>{ago(it.at, t)}</em>
      </button>
      {it.type === 'session.waiting' && approvable.has(it.session) && <div className="tt-inbox-acts">
        <button type="button" className="tt-act ok" disabled={!!acting} onClick={() => void answer(it, 'Enter')}><CheckIcon size={14} />{t('mobile.home.allow')}</button>
        <button type="button" className="tt-act danger" disabled={!!acting} onClick={() => void answer(it, 'Escape')}><CloseIcon size={14} />{t('mobile.home.deny')}</button>
      </div>}
    </div>
  )
  const section = (title: string, list: InboxItem[]) => list.length ? (
    <section className="tt-inbox-sec"><h3>{title} <span>{list.length}</span></h3>{list.map(row)}</section>
  ) : null

  return (
    <div className="tt-inbox">
      <div className="tt-pagehead">
        <div className="ttl"><div className="kicker">{t('inbox.kicker')}</div><h2>{t('nav.inbox')}</h2><p>{t('inbox.desc')}</p></div>
        {!isMobile && unread && <div className="acts"><Button size="small" type="text" onClick={() => markRead('all')}>{t('inbox.readAll')}</Button></div>}
      </div>
      {isMobile && <div className="tt-inbox-filters">
        {(['all', 'waiting', 'done', 'error', 'unread'] as const).map((key) => <button key={key} type="button" className="tt-inbox-filter" aria-pressed={filter === key} onClick={() => setFilter(key)}>{t(key === 'all' ? 'mobile.filter.all' : key === 'unread' ? 'inbox.unread' : key === 'error' ? 'inbox.errors' : `inbox.${key}`)}</button>)}
        {unread && filter === 'unread' && <button type="button" className="tt-inbox-readall" onClick={() => void markRead('all')}>{t('inbox.readAll')}</button>}
      </div>}
      {loadError && <div className="tt-data-error" role="alert">{t('inbox.loadFailed')} <button type="button" className="tt-act" onClick={() => void load()}>{t('inbox.retry')}</button></div>}
      {!visible.length && !loadError && <div className="tt-inbox-empty"><span className="tt-inbox-empty-icon">{ICONS.inbox}</span><p>{t(filter === 'all' ? 'inbox.empty' : 'inbox.emptyFilter')}</p></div>}
      {section(t('inbox.waiting'), waiting)}
      {section(t('inbox.done'), done)}
      {section(t('inbox.errors'), errors)}
    </div>
  )
}
