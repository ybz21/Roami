import { ArchiveIcon, ChevronRight } from '../../icons'
import { useI18n } from '../../i18n'
import type { AgentSnapshot } from './agent-protocol'

export default function AgentCompactionStatus({ value, onOpen }: { value: AgentSnapshot['compaction']; onOpen: () => void }) {
  const { t } = useI18n()
  if (!value) return null
  const active = ['queued', 'running', 'started'].includes(value.state)
  const state = ['completed', 'cancelled', 'failed', 'skipped'].includes(value.state) ? value.state : 'unknown'
  return <div className="agent-compaction-status" role="status" data-state={value.state}>
    <button type="button" onClick={onOpen}>
      <ArchiveIcon size={16} /><span>{t(active ? 'agent.compacting' : 'agent.compaction.' + state)}</span>
      <small>{t('agent.context.view')}</small><ChevronRight size={16} />
    </button>
  </div>
}
