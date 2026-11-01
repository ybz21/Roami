import { useEffect, useState } from 'react'
import { Alert, Button, Popconfirm, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { gatewayAgentNames } from './gateway-agent'
import { catalogFailure } from './model-hub-api'

type LocalSource = { id: string; revision: string; agentKind: string; name: string; baseUrl: string; protocol: string; model: string; hasKey: boolean; unavailable: boolean }
export default function LocalModelSources({ onImported }: { onImported: () => void }) {
  const { t } = useI18n()
  const [value, setValue] = useState<{ revision: string; sources: LocalSource[] } | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(''), [version, setVersion] = useState(0)
  useEffect(() => {
    const abort = new AbortController(); setError('')
    void api('GET', '/agent/model-gateway/catalog/local-sources', undefined, { signal: abort.signal }).then(({ data }) => { if (!abort.signal.aborted) setValue(data) }).catch(cause => { if (!abort.signal.aborted) setError(catalogFailure(cause)) })
    return () => abort.abort()
  }, [version])
  const importSource = async (row: LocalSource) => {
    if (busy || !value) return
    setBusy(row.id); setError('')
    try {
      await api('POST', '/agent/model-gateway/catalog/local-sources', { id: row.id, revision: row.revision, catalogRevision: value.revision })
      onImported()
    } catch (cause) { setError((cause as { apiError?: { code?: string } })?.apiError?.code === 'MODEL_LOCAL_SOURCE_EXISTS' ? 'hub.local.exists' : catalogFailure(cause)) }
    finally { setBusy('') }
  }
  return <section className="tt-model-hub-scroll">
    <p className="agent-settings-hint">{t('hub.local.hint')}</p>
    {error && <Alert type="error" role="alert" message={t(error)} action={<Button disabled={!!busy} onClick={() => setVersion(value => value + 1)}>{t('capabilities.models.reread')}</Button>} />}
    {!value && !error && <Spin />}
    {value && !value.sources.length && <p>{t('hub.local.empty')}</p>}
    {value?.sources.map(row => <article key={row.id} className="tt-model-hub-row" aria-label={row.name}>
      <div><strong>{row.name}</strong><small>{gatewayAgentNames[row.agentKind]}</small><small>{row.baseUrl}</small>{row.unavailable && <small>{t('hub.local.unsupported')}</small>}</div>
      <Popconfirm classNames={{ root: 'tt-model-connection-confirm' }} title={t('hub.local.confirm')} description={t('hub.local.scope')} onConfirm={() => importSource(row)} okText={t('hub.local.import')} cancelText={t('common.cancel')}><Button disabled={!!busy || row.unavailable} loading={busy === row.id}>{t('hub.local.import')}</Button></Popconfirm>
    </article>)}
  </section>
}
