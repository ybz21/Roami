import { useI18n } from '../../i18n'

export default function AgentPageBoundary({ more, loading, failed, load, earlier = false }: { more: boolean; loading: boolean; failed: boolean; load: () => void; earlier?: boolean }) {
  const { t } = useI18n()
  if (!more && !failed && !loading) return null
  return <div className="agent-page-boundary" aria-live="polite">
    {failed && <span role="alert">{t('agent.requestFailed')}</span>}
    <button type="button" className="tt-act" disabled={loading} onClick={load}>{t(loading ? 'agent.pagination.loading' : failed ? 'agent.retry' : earlier ? 'agent.pagination.earlier' : 'agent.pagination.more')}</button>
  </div>
}
