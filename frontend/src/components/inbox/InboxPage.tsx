// 收件箱（24 稿 §5）：会话级事件的时间线——需要你 / 刚做完 / 出错了。手机版的首页，桌面也能看。
// 数据来自 GET /inbox（后端从台账 plugin_notifications 里筛 source=roam.web）。
import { useEffect, useRef, useState } from 'react'
import { Button, Empty, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { setBadge } from '../../push'
import { AgentLogo, CloseIcon } from '../../icons'

export type InboxItem = { id: number; type: string; session: string; label: string; body: string; at: number; read: boolean }

function ago(sec: number, t: (k: string, p?: any) => string): string {
  const d = Math.max(0, Math.floor(Date.now() / 1000 - sec))
  if (d < 60) return t('time.justNow')
  if (d < 3600) return `${Math.floor(d / 60)}m`
  if (d < 86400) return `${Math.floor(d / 3600)}h`
  return `${Math.floor(d / 86400)}d`
}

export default function InboxPage({ onOpenSession, openOnMount }: { onOpenSession: (name: string) => void; openOnMount?: string }) {
  const { t } = useI18n()
  const [items, setItems] = useState<InboxItem[] | null>(null)
  const opened = useRef(false)

  const load = async () => {
    try {
      const r = await api('GET', '/inbox?limit=100')
      setItems(r.data.items || [])
      setBadge(r.data.badge || 0)
    } catch { setItems((cur) => cur || []) }
  }
  useEffect(() => {
    void load()
    const i = setInterval(load, 10000)
    return () => clearInterval(i)
  }, [])
  // 从通知点进来：#/inbox/<session> → 直接开那个会话，收件箱只是落脚点
  useEffect(() => {
    if (openOnMount && !opened.current) { opened.current = true; onOpenSession(openOnMount) }
  }, [openOnMount, onOpenSession])

  const markRead = async (ids: number[] | 'all') => {
    setItems((cur) => (cur || []).map((it) => (ids === 'all' || ids.includes(it.id) ? { ...it, read: true } : it)))
    try { const r = await api('POST', '/inbox/read', ids === 'all' ? { all: true } : { ids }); setBadge(r.data?.badge || 0) } catch { /* 下轮刷新会对齐 */ }
  }
  const open = (it: InboxItem) => { if (!it.read) void markRead([it.id]); onOpenSession(it.session) }

  if (items === null) return <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}><Spin /></div>
  const waiting = items.filter((x) => x.type === 'session.waiting')
  const done = items.filter((x) => x.type === 'session.done')
  const errors = items.filter((x) => x.type === 'session.error')
  const unread = items.some((x) => !x.read)

  const row = (it: InboxItem) => (
    <button key={it.id} type="button" className={`tt-inbox-row${it.read ? '' : ' unread'} ${it.type.split('.')[1]}`} onClick={() => open(it)}>
      <span className="ic">{it.type === 'session.waiting' ? '!' : it.type === 'session.error' ? <CloseIcon size={12} /> : '✓'}</span>
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
        <div className="kicker">{t('inbox.kicker')}</div>
        <div className="row"><h1>{t('nav.inbox')}</h1>{unread && <Button size="small" type="text" onClick={() => markRead('all')}>{t('inbox.readAll')}</Button>}</div>
        <div className="desc">{t('inbox.desc')}</div>
      </div>
      {!items.length && <Empty description={t('inbox.empty')} image={<AgentLogo kind="claude" size={28} />} />}
      {section(t('inbox.waiting'), waiting)}
      {section(t('inbox.done'), done)}
      {section(t('inbox.errors'), errors)}
    </div>
  )
}
