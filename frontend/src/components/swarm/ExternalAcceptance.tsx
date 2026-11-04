import { useEffect, useState } from 'react'
import { App, Button, Input, Select } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { nodeApi } from '../cluster/node-url'
import type { SwarmWork } from './swarm-protocol'

export default function ExternalAcceptance({ work, onAccepted }: { work: SwarmWork; onAccepted: () => Promise<void> }) {
  const { t } = useI18n(), { message } = App.useApp()
  const key = 'roami.swarm.acceptance:' + nodeApi('/agent/tasks/' + work.task_id) + ':' + work.revision
  const [saved] = useState(() => { try { return JSON.parse(localStorage.getItem(key) || '{}') } catch { return {} } })
  const [target, setTarget] = useState<string>(saved.target || ''), [artifactId, setArtifactId] = useState<string>(saved.artifactId || ''), [busy, setBusy] = useState(false)
  useEffect(() => { localStorage.setItem(key, JSON.stringify({ target, artifactId })) }, [key, target, artifactId])
  const artifacts = work.evidence?.artifacts || []
  const accept = async () => {
    if (busy || !target.trim() || !artifacts.some(item => item.id === artifactId)) return
    setBusy(true)
    try {
      await api('POST', `/agent/tasks/${encodeURIComponent(work.task_id!)}/verify`, { accepted: true, revision: work.revision, runId: work.attempt?.runId, evidence: { artifactId, target: target.trim(), state: 'confirmed' } })
      localStorage.removeItem(key); await onAccepted()
    } catch { message.error(t('swarm.managed.actionFailed')) } finally { setBusy(false) }
  }
  return <section className="swarm-external-acceptance">
    <p>{t('swarm.managed.externalAcceptance')}</p>
    <label>{t('swarm.managed.receipt')}<Select aria-label={t('swarm.managed.receipt')} value={artifactId || undefined} onChange={setArtifactId} disabled={busy} options={artifacts.map(item => ({ value: item.id, label: item.name }))} /></label>
    <label>{t('swarm.managed.externalTarget')}<Input aria-label={t('swarm.managed.externalTarget')} value={target} onChange={event => setTarget(event.target.value)} disabled={busy} /></label>
    <Button loading={busy} disabled={busy || !target.trim() || !artifacts.some(item => item.id === artifactId)} onClick={() => void accept()}>{t('agent.task.accept')}</Button>
  </section>
}
