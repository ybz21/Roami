import { useEffect, useRef, useState } from 'react'
import { ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { usePageActive } from '../../page-activity'
import BackButton from '../BackButton'
import MobileSubPage from '../MobileSubPage'
import { useGatewayRequests } from './gateway-request-api'
import { Alert, Button, Select, Spin } from './model-controls'
import type { ModelCatalog } from './model-hub-api'
import './gateway-request.css'
import './gateway-request-audit.css'

const outcomes = ['success', 'recovered', 'blocked', 'exhausted', 'interrupted', 'failed', 'uncertain']

export default function GatewayRequestAudit({ active, catalog, onBack, onRequest }: {
  active: boolean; catalog: ModelCatalog; onBack: () => void; onRequest: (id: string) => void
}) {
  const { t, locale } = useI18n()
  const { phone } = useLayout()
  const pageActive = usePageActive()
  const [hours, setHours] = useState(6)
  const [route, setRoute] = useState('')
  const [outcome, setOutcome] = useState('')
  const openedRow = useRef<HTMLButtonElement | null>(null)
  const state = useGatewayRequests(active && pageActive, hours, route, '', outcome, null)
  const title = t('gatewayTrace.audit')
  const routeNames = new Map([...Object.entries(state.data?.routes || {}), ...catalog.models.map(model => [model.id, model.name] as const)])
  if (route && !routeNames.has(route)) routeNames.set(route, route)
  const time = new Intl.DateTimeFormat(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })

  useEffect(() => {
    if (active && openedRow.current?.isConnected) openedRow.current.focus({ preventScroll: true })
  }, [active])

  const select = (label: string, value: string, options: { value: string; label: string }[], change: (value: string) => void) => (
    <label className="agent-settings-field">{label}<Select virtual={false} aria-label={label} value={value} options={options} onChange={change} /></label>
  )
  const content = <>
    <div className="tt-request-audit-filters">
      <label className="agent-settings-field">{t('monitor.range')}<Select<number> aria-label={t('monitor.range')} value={hours} options={[1, 6, 24].map(value => ({ value, label: t('monitor.hours', { hours: value }) }))} onChange={setHours} /></label>
      {select(t('monitor.model'), route, [{ value: '', label: t('monitor.allModels') }, ...[...routeNames].map(([value, label]) => ({ value, label }))], setRoute)}
      {select(t('modelUsage.state'), outcome, [{ value: '', label: t('modelUsage.allStates') }, ...outcomes.map(value => ({ value, label: t('gatewayTrace.' + value) }))], setOutcome)}
    </div>
    {state.failed && <Alert type="error" role="alert" message={t('monitor.failed')} action={<Button onClick={state.retry}>{t('agent.retry')}</Button>} />}
    {state.unsupported && <p className="agent-settings-hint">{t('gatewayTrace.unsupported')}</p>}
    {state.pending ? <Spin /> : state.data && (
      state.data.recent.length ? <>
        <ul className="tt-request-list">
          {state.data.recent.map(row => <li key={row.requestId}>
            <button type="button" className="tt-act" onClick={event => { openedRow.current = event.currentTarget; onRequest(row.requestId) }}>
              <span className="tt-request-row-model"><strong>{routeNames.get(row.routeId) || row.model}</strong><small>{row.caller === 'external' ? t('hub.gateway.externalClient') : row.caller} · {time.format(row.at)}</small></span>
              <span className="tt-request-row-result"><strong className={'tt-request-outcome is-' + row.outcome}>{t('gatewayTrace.' + row.outcome)}</strong>{row.status > 0 && <small>HTTP {row.status}</small>}</span>
              <ChevronRight />
            </button>
          </li>)}
        </ul>
        {state.data.recent.length === 50 && <p className="agent-settings-hint">{t('gatewayTrace.recentLimit')}</p>}
      </> : <p className="agent-settings-hint">{t(route || outcome ? 'hub.directory.noMatches' : 'gatewayTrace.empty')}</p>
    )}
  </>

  if (phone) return active ? <MobileSubPage title={title} onBack={onBack} search={false} manageHistory={false}>{content}</MobileSubPage> : null
  return <section className="tt-request-detail tt-request-audit" hidden={!active} aria-label={title}>
    <header className="tt-pagehead"><BackButton onClick={onBack} /><h2>{title}</h2></header>
    <div className="tt-request-detail-scroll" aria-busy={state.pending}>{content}</div>
  </section>
}
