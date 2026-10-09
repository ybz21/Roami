// 会话通知记录：需要你 / 刚做完 / 出错了。
// 数据来自 GET /inbox（后端从台账 plugin_notifications 里筛 source=roam.web）。
import { useEffect, useState } from 'react'
import { Button, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { setBadge } from '../../push'
import { CheckIcon, CloseIcon, QuestionIcon } from '../../icons'
import { ICONS } from '../nav-icons'

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
  const [items, setItems] = useState<InboxItem[] | null>(null)
  const [loadError, setLoadError] = useState(false)

  const load = async () => {
    try {
      const [r, overview] = await Promise.all([api('GET', '/inbox?limit=100'), api('GET', '/sessions/overview')])
      const active = new Set((overview.data.items || []).filter((s: { waiting: boolean }) => s.waiting).map((s: { name: string }) => s.name))
      const next: InboxItem[] = (r.data.items || []).filter((it: InboxItem) => it.type !== 'session.waiting' || active.has(it.session))
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

  if (items === null) return <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}><Spin /></div>
  const waiting = items.filter((x) => x.type === 'session.waiting')
  const done = items.filter((x) => x.type === 'session.done')
  const errors = items.filter((x) => x.type === 'session.error')
  const unread = items.some((x) => !x.read)

  const row = (it: InboxItem) => (
    <button key={it.id} type="button" className={`tt-inbox-row${it.read ? '' : ' unread'} ${it.type.split('.')[1]}`} onClick={() => open(it)}>
      <span className="ic">{it.type === 'session.waiting' ? <QuestionIcon size={12} /> : it.type === 'session.error' ? <CloseIcon size={12} /> : <CheckIcon size={12} />}</span>
      <span className="t"><b>{it.label || it.session}</b><span>{it.body || t('inbox.noSummary')}</span></span>
      <em>{ago(it.at, t)}</em>
    </button>
  )
  const section = (title: string, list: InboxItem[]) => list.length ? (
    <section className="tt-inbox-sec"><h3>{title} <span>{list.length}</span></h3>{list.map(row)}</section>
  ) : null

  return (
    <div className="tt-inbox">
      <div className="tt-pagehead">
        <div className="ttl"><div className="kicker">{t('inbox.kicker')}</div><h2>{t('nav.inbox')}</h2><p>{t('inbox.desc')}</p></div>
        {unread && <div className="acts"><Button size="small" type="text" onClick={() => markRead('all')}>{t('inbox.readAll')}</Button></div>}
      </div>
      {loadError && <div className="tt-data-error" role="alert">{t('inbox.loadFailed')} <button type="button" className="tt-act" onClick={() => void load()}>{t('inbox.retry')}</button></div>}
      {!items.length && !loadError && <div className="tt-inbox-empty"><span className="tt-inbox-empty-icon">{ICONS.inbox}</span><p>{t('inbox.empty')}</p></div>}
      {section(t('inbox.waiting'), waiting)}
      {section(t('inbox.done'), done)}
      {section(t('inbox.errors'), errors)}
    </div>
  )
}
