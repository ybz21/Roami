import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { Button, Spin } from './model-controls'
import MagpieCallHistory from './MagpieCallHistory'
import type { PluginProvider } from './magpie-provider'
import './magpie-account-capabilities.css'

type QuotaWindow = { name: string; display?: string; balance: number | null; limit: number; unit: string; used: number | null; resetsAt?: string }
type Quota = { plan?: string; balance?: string; windows?: QuotaWindow[] }
const outcomes = ['claimed', 'done', 'ineligible', 'inactive', 'captcha', 'failed'] as const
type CheckIn = { outcome: typeof outcomes[number]; credit: number; streak: number; until?: string }

export default function MagpieAccountCapabilities({ path, provider, disabled = false }: {
  path: string; provider: PluginProvider; disabled?: boolean
}) {
  const { usage, checkin, calls } = provider
  const [historyOpen, setHistoryOpen] = useState(false)
  const { t, locale } = useI18n()
  const [quota, setQuota] = useState<Quota | null>(null), [error, setError] = useState(''), [loading, setLoading] = useState(usage)
  const [result, setResult] = useState<CheckIn | null>(null), [checkInError, setCheckInError] = useState(''), [checking, setChecking] = useState(false)
  const [revision, setRevision] = useState(0)
  const operation = useRef<AbortController | null>(null)
  useEffect(() => () => { operation.current?.abort() }, [])
  useEffect(() => {
    if (!usage) return
    const request = new AbortController()
    setLoading(true); setError('')
    void api('GET', path + '/usage', undefined, { signal: request.signal }).then(({ data }) => {
      if (!request.signal.aborted) setQuota(data)
    }).catch(cause => {
      if (!request.signal.aborted) setError(cause?.apiError?.code === 'MODEL_PLUGIN_SIGN_IN_FAILED' ? 'hub.plugin.signInFailed' : 'hub.plugin.quotaUnavailable')
    }).finally(() => { if (!request.signal.aborted) setLoading(false) })
    return () => request.abort()
  }, [path, revision, usage])
  const checkIn = async () => {
    if (operation.current || disabled) return
    const request = new AbortController()
    operation.current = request
    setChecking(true); setResult(null); setCheckInError('')
    try {
      const { data } = await api('POST', path + '/check-in', {}, { signal: request.signal })
      if (request.signal.aborted) return
      if (!outcomes.includes(data?.outcome)) { setCheckInError('hub.plugin.checkInUnconfirmed'); return }
      setResult(data)
      if (data.outcome === 'claimed' || data.outcome === 'done') setRevision(value => value + 1)
    } catch (cause: any) {
      if (!request.signal.aborted) setCheckInError(cause?.apiError?.code === 'MODEL_PLUGIN_BUSY' ? 'hub.plugin.busy' : 'hub.plugin.checkInUnconfirmed')
    } finally {
      operation.current = null
      if (!request.signal.aborted) setChecking(false)
    }
  }
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 })
  const date = (value?: string) => value && Number.isFinite(Date.parse(value)) ? new Intl.DateTimeFormat(locale, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : ''
  const complete = result?.outcome === 'claimed' || result?.outcome === 'done'
  const next = date(result?.until)

  return <section className="tt-magpie-account-capabilities" aria-label={t('hub.plugin.accountCapabilities')}>
    {usage && <div>
      <div className="tt-magpie-capability-head"><h4>{t('hub.plugin.accountQuota')}</h4>{error && <Button disabled={disabled || loading} onClick={() => setRevision(value => value + 1)}>{t('agent.retry')}</Button>}</div>
      {loading ? <Spin /> : error ? <p role="status">{t(error)}</p> : quota && <>
        {(quota.plan || quota.balance) && <p>{[quota.plan, quota.balance].filter(Boolean).join(' · ')}</p>}
        {!!quota.windows?.length && <dl>{quota.windows.map((window, index) => <div key={index}>
          <dt>{window.name || t('hub.plugin.accountQuota')}</dt>
          <dd>{window.display || (window.balance != null ? [number.format(window.balance), window.unit].filter(Boolean).join(' ')
            : window.used != null ? number.format(window.used) + '%' : t('monitor.pending'))}
            {date(window.resetsAt) && <small>{t('hub.plugin.quotaReset', { time: date(window.resetsAt) })}</small>}
          </dd>
        </div>)}</dl>}
        {!quota.plan && !quota.balance && !quota.windows?.length && <p>{t('monitor.pending')}</p>}
      </>}
    </div>}
    {checkin && <div>
      <div className="tt-magpie-capability-head"><h4>{t('hub.plugin.checkIn')}</h4><Button loading={checking} disabled={disabled || complete} onClick={() => void checkIn()}>{t(complete ? 'hub.plugin.checkIn.done' : 'hub.plugin.checkInNow')}</Button></div>
      {(result || checkInError) && <p role="status">
        {checkInError ? t(checkInError) : result?.outcome !== 'done' && t('hub.plugin.checkIn.' + result!.outcome, { credit: number.format(result!.credit) })}
        {result && result.streak > 0 && <small>{t('hub.plugin.checkInStreak', { count: number.format(result.streak) })}</small>}
        {next && <small>{t('hub.plugin.checkInNext', { time: next })}</small>}
      </p>}
    </div>}
    {calls && <div><details onToggle={event => setHistoryOpen(event.currentTarget.open)}>
      <summary>{t('hub.plugin.callHistory')}</summary>
      {historyOpen && <MagpieCallHistory path={path} />}
    </details></div>}
  </section>
}
