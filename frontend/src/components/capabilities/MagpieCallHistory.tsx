import { useEffect, useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { Button, Spin } from './model-controls'

type Call = { t: number; model: string; in: number; out: number; cost: number | null }

export default function MagpieCallHistory({ path }: { path: string }) {
  const { t, locale } = useI18n()
  const [calls, setCalls] = useState<Call[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const request = new AbortController()
    void api('GET', path + '/calls', undefined, { signal: request.signal }).then(({ data }) => {
      if (!request.signal.aborted) setCalls(data)
    }).catch(() => {
      if (!request.signal.aborted) setFailed(true)
    })
    return () => request.abort()
  }, [path, revision])
  if (failed) return <p role="status">{t('hub.plugin.callsUnavailable')} <Button onClick={() => { setFailed(false); setRevision(value => value + 1) }}>{t('agent.retry')}</Button></p>
  if (!calls) return <Spin />
  if (!calls.length) return <p>{t('hub.plugin.noRecentCalls')}</p>
  const date = new Intl.DateTimeFormat(locale, { timeStyle: 'short', dateStyle: 'short' })
  const number = new Intl.NumberFormat(locale)
  const money = new Intl.NumberFormat(locale, { style: 'currency', currency: 'USD', maximumFractionDigits: 6 })
  return <>
    <p className="agent-settings-hint">{t('hub.plugin.callsLastDay')}</p>
    <dl>{calls.map((call, index) => <div key={index}>
      <dt>{call.model || t('hub.plugin.callModelUnknown')}<small>{date.format(call.t)}</small></dt>
      <dd>{t('hub.plugin.callTokens', { input: number.format(call.in), output: number.format(call.out) })}
        {call.cost != null && <small>{money.format(call.cost)}</small>}
      </dd>
    </div>)}</dl>
  </>
}
