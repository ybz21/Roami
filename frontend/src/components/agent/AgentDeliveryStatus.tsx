import { useEffect, useState } from 'react'
import { Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'

type Delivery = { id: string; conversationId: string; messageId: string; attempts: number; updatedMs: number | null; outcome: { stage: string; accepted?: number } }
const stages = new Set(['pending', 'sending', 'adapter_accepted', 'failed', 'unknown', 'no_devices', 'suppressed', 'disabled', 'deferred'])

export default function AgentDeliveryStatus({ select }: { select: (cid: string) => void }) {
  const { t, locale } = useI18n()
  const [items, setItems] = useState<Delivery[] | null>(null), [failed, setFailed] = useState(false), [version, setVersion] = useState(0)
  useEffect(() => {
    let cancelled = false
    const abort = new AbortController(), timer = setTimeout(() => abort.abort(), 10000)
    void api('GET', '/agent/notification-deliveries', undefined, { signal: abort.signal })
      .then((result) => { if (!cancelled) { setItems(result.data); setFailed(false) } })
      .catch(() => { if (!cancelled) setFailed(true) }).finally(() => clearTimeout(timer))
    return () => { cancelled = true; clearTimeout(timer); abort.abort() }
  }, [version])
  return <div className="agent-notifications-body">
    <p className="agent-muted">{t('agent.notification.deliveryHint')}</p>
    <button type="button" className="tt-act" onClick={() => setVersion((value) => value + 1)}>{t('agent.retry')}</button>
    {!items && !failed && <Spin />}{failed && <p role="alert">{t('agent.requestFailed')}</p>}
    {items?.length === 0 && <p className="agent-muted">{t('agent.notification.noDeliveries')}</p>}
    {items?.map((item) => <div className="agent-notification-record" key={item.id}><b>{t('agent.notification.delivery.' + (stages.has(item.outcome.stage) ? item.outcome.stage : 'unknown'))}</b><span className="agent-muted">{t('agent.notification.attempts', { n: item.attempts })}{item.updatedMs ? ' · ' + new Date(item.updatedMs).toLocaleString(locale) : ''}</span><button type="button" className="tt-act" onClick={() => select(item.conversationId)}>{t('agent.notification.openConversation')}</button></div>)}
  </div>
}
