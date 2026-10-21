import type { RegisteredAgent } from '../../agent-registry'
import { useI18n } from '../../i18n'

export function AgentBalance({ agent, detail = false, id }: { agent?: RegisteredAgent; detail?: boolean; id?: string }) {
  const { t, locale } = useI18n()
  const q = agent?.quota
  const windows = q?.state === 'available' ? (q.windows?.length ? q.windows : q.remainingPercent !== undefined ? [{ remainingPercent: q.remainingPercent, windowMinutes: q.windowMinutes || 0, resetsAt: q.resetsAt }] : []).filter(window => !window.resetsAt || window.resetsAt * 1000 > Date.now()) : []
  const reason = q?.reason || 'no_snapshot'
  return <span className="agent-balance" id={id}>
    {windows.length ? windows.map((window, index) => <span className="agent-balance-window" key={index}>
      <span className="agent-balance-values"><span>{t(window.windowMinutes % 1440 === 0 ? 'agent.professional.periodDays' : 'agent.professional.periodHours', { n: window.windowMinutes % 1440 === 0 ? window.windowMinutes / 1440 : Number((window.windowMinutes / 60).toFixed(1)) })}</span><strong>{t('agent.professional.remaining', { percent: Math.round(window.remainingPercent) })}</strong></span>
      <progress className="agent-balance-meter" aria-label={t('agent.professional.remaining', { percent: Math.round(window.remainingPercent) })} max={100} value={Math.max(0, Math.min(100, window.remainingPercent))} />
      {window.resetsAt && <span className="agent-balance-reset">{t('agent.professional.resetsAt', { time: new Date(window.resetsAt * 1000).toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) })}</span>}
    </span>) : <span className="agent-balance-unavailable">{t(`agent.professional.reason.${reason}`)}</span>}
    {detail && !!windows.length && q?.observedAt && <span className="agent-settings-hint">{t('agentDiscovery.observed', { time: new Date(q.observedAt).toLocaleString(locale) })}</span>}
  </span>
}
