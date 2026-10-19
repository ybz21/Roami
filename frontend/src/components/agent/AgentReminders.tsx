import { useEffect, useRef, useState } from 'react'
import { Popconfirm, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'

type BriefGeneration = { messageId?: string; dayKey?: string; state: 'queued' | 'running' | 'done' | 'failed'; skipped?: string; generationUnknown?: boolean }
type Reminder = { id: string; conversationId: string; branchId?: string; lastGeneration?: BriefGeneration; enabled: boolean; nextDueMs: number | null; spec: { text: string; dailyAt: string | null; timezone: string } }

function briefState(generation: BriefGeneration) {
  return generation.generationUnknown ? 'unknown' : generation.skipped ? 'skipped' : generation.state
}

export default function AgentReminders({ select }: { select: (cid: string, branch?: string, message?: string) => void }) {
  const { t, locale } = useI18n()
  const [items, setItems] = useState<Reminder[] | null>(null), [failed, setFailed] = useState(false), [version, setVersion] = useState(0), [busy, setBusy] = useState('')
  const alive = useRef(true), pending = useRef(false)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => { const timer = setInterval(() => { if (!pending.current && document.visibilityState === 'visible') setVersion((value) => value + 1) }, 15000); return () => clearInterval(timer) }, [])
  useEffect(() => {
    let cancelled = false
    const abort = new AbortController(), timer = setTimeout(() => abort.abort(), 10000)
    void api('GET', '/agent/reminders', undefined, { signal: abort.signal })
      .then((result) => { if (!cancelled) { setItems(result.data); setFailed(false) } })
      .catch(() => { if (!cancelled) setFailed(true) }).finally(() => clearTimeout(timer))
    return () => { cancelled = true; clearTimeout(timer); abort.abort() }
  }, [version])
  const cancel = async (id: string) => {
    if (pending.current) return
    pending.current = true; setBusy(id)
    try { await api('DELETE', '/agent/reminders/' + encodeURIComponent(id)); if (alive.current) setVersion((value) => value + 1) }
    catch { if (alive.current) setFailed(true) }
    finally { pending.current = false; if (alive.current) setBusy('') }
  }
  return <div className="agent-notifications-body">
    <p className="agent-muted">{t('agent.notification.remindersHint')}</p>
    {!items && !failed && <Spin />}
    {failed && <p role="alert">{t('agent.requestFailed')}<button type="button" className="tt-act" onClick={() => setVersion((value) => value + 1)}>{t('agent.retry')}</button></p>}
    {items?.length === 0 && <p className="agent-muted">{t('agent.notification.noReminders')}</p>}
    {items?.map((item) => <div className="agent-notification-record" key={item.id}><p>{item.spec.text}</p><span className="agent-muted">{item.nextDueMs && item.enabled ? new Date(item.nextDueMs).toLocaleString(locale, { timeZone: item.spec.timezone, dateStyle: 'short', timeStyle: 'short' }) + ' · ' + item.spec.timezone : t('agent.notification.reminderInactive')}</span>{item.spec.dailyAt && <span className="agent-muted">{t('agent.notification.dailyAt', { time: item.spec.dailyAt, timezone: item.spec.timezone })}</span>}{item.lastGeneration && <span className="agent-muted" role="status">{t('agent.notification.lastBrief', { day: item.lastGeneration.dayKey || '', status: t('agent.notification.briefState.' + briefState(item.lastGeneration)) })}</span>}<div className="agent-task-actions"><button type="button" className="tt-act" onClick={() => select(item.conversationId, item.branchId, item.lastGeneration?.messageId)}>{t('agent.notification.openConversation')}</button>{item.enabled && <Popconfirm title={t('agent.notification.cancelReminder')} okText={t('agent.notification.confirmCancel')} cancelText={t('agent.notification.keepReminder')} onConfirm={() => cancel(item.id)}><button type="button" className="tt-act" disabled={!!busy}>{t('agent.notification.cancelReminder')}</button></Popconfirm>}</div></div>)}
  </div>
}
