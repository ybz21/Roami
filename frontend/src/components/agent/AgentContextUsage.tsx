import { useI18n } from '../../i18n'
import { useAgentContext } from './useAgentContext'

export default function AgentContextUsage({ cid, node, model, revision, active, onOpen }: { cid: string; node: string | null; model: string; revision: string; active: boolean; onOpen: () => void }) {
  const { t, locale } = useI18n(), { data, failed } = useAgentContext(cid, node, model, revision, active)
  if (!cid) return null
  const format = (value: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: value < 1000 ? 0 : 1 }).format(value >= 1000000 ? value / 1000000 : value >= 1000 ? value / 1000 : value) + (value >= 1000000 ? 'M' : value >= 1000 ? 'K' : '')
  const capacity = data?.contextWindow && Number.isFinite(data.contextWindow) && data.contextWindow > 0 ? data.contextWindow : null
  const percent = data && capacity ? new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(data.estimatedTokens / capacity) : ''
  const nearLimit = !!(data && data.compactionThreshold && data.estimatedTokens >= data.compactionThreshold)
  const short = data ? capacity ? t('agent.contextMeter.known', { used: format(data.estimatedTokens), capacity: format(capacity), percent }) : t('agent.contextMeter.unknown', { used: format(data.estimatedTokens) }) : t(failed ? 'agent.contextMeter.unavailable' : 'agent.contextMeter.loading')
  const label = short + (failed && data ? t('agent.contextMeter.stale') : '')
  const details = data ? capacity ? t('agent.contextUsage', { used: data.estimatedTokens.toLocaleString(locale), budget: capacity.toLocaleString(locale) }) : t('agent.contextUnknown', { used: data.estimatedTokens.toLocaleString(locale) }) : label
  return <button type="button" className={`tt-act agent-context-meter${nearLimit ? ' is-near-limit' : ''}${failed ? ' is-stale' : ''}`} aria-label={label} title={details} onClick={onOpen}>
    <span>{label}</span>
  </button>
}
