import { useEffect, useState } from 'react'
import { App, Button, Input } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { nodeApi } from '../cluster/node-url'
import Markdown from '../markdown/Markdown'
import type { SwarmSnapshot } from './swarm-protocol'

type Props = { data: SwarmSnapshot; onSaved: () => Promise<void>; onReload: () => Promise<void> }
type Draft = { content: string; expectedSha256: string | null }

export default function TeamMemory(props: Props) {
  const { t } = useI18n(), memory = props.data.teamMemory
  if (!memory?.available || typeof memory.content !== 'string' || typeof memory.sha256 !== 'string') return <section className="swarm-memory" aria-label={t('swarm.managed.memory')}><p role="alert">{t('swarm.managed.memoryUnavailable')}</p></section>
  return <MemoryEditor {...props} content={memory.content} sha256={memory.sha256} />
}

function MemoryEditor({ data, content, sha256, onSaved, onReload }: Props & { content: string; sha256: string }) {
  const { t } = useI18n(), { message } = App.useApp()
  const key = 'roami.swarm.memory:' + nodeApi('/agent/swarms/' + data.id)
  const [draft, setDraft] = useState<Draft>(() => {
    const stored = localStorage.getItem(key)
    if (stored !== null) {
      try {
        const value = JSON.parse(stored)
        if (typeof value?.content === 'string' && (typeof value.expectedSha256 === 'string' || value.expectedSha256 === null)) return value
      } catch { /* Older drafts contain only text and need an explicit merge. */ }
      return { content: stored, expectedSha256: null }
    }
    return { content, expectedSha256: sha256 }
  })
  const [saving, setSaving] = useState(false), changed = draft.expectedSha256 !== sha256
  useEffect(() => {
    if (draft.content === content && draft.expectedSha256 === sha256) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify(draft))
  }, [key, draft])
  const save = async () => {
    if (changed || !draft.expectedSha256 || saving) return
    setSaving(true)
    try {
      await api('PUT', `/agent/swarms/${encodeURIComponent(data.id)}/memory`, draft)
      localStorage.removeItem(key); await onSaved()
    } catch (error) {
      if ((error as { status?: number }).status === 409) await onReload().catch(() => {})
      message.error(t('swarm.managed.memoryFailed'))
    } finally { setSaving(false) }
  }
  return <section className="swarm-memory" aria-label={t('swarm.managed.memory')}>
    <p className="swarm-note">{data.teamMemory?.source}</p>
    {changed && <div role="status"><p>{t('swarm.managed.memoryChanged')}</p><Markdown>{content}</Markdown><Button disabled={saving || data.archived} onClick={() => setDraft(value => ({ ...value, expectedSha256: sha256 }))}>{t('swarm.managed.memoryMerged')}</Button></div>}
    <Input.TextArea aria-label={t('swarm.managed.memory')} value={draft.content} onChange={event => setDraft(value => ({ ...value, content: event.target.value }))} rows={12} disabled={saving || data.archived} />
    <div className="swarm-detail-actions"><Button disabled={data.archived || changed || saving || draft.content === content} loading={saving} onClick={() => void save()}>{t('swarm.managed.memorySave')}</Button></div>
    {!changed && <details><summary>{t('agent.memory')}</summary>{content ? <Markdown>{content}</Markdown> : <p className="swarm-note">{t('swarm.managed.memoryEmpty')}</p>}</details>}
  </section>
}
