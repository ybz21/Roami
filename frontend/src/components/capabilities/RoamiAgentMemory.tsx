import { useEffect, useState } from 'react'
import { Button } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useCurrentNodeId } from '../cluster/node-url'
import AgentMemory from '../agent/AgentMemory'
import BackButton from '../BackButton'
import { useLayout } from '../../layout'
import './model-hub.css'

export default function RoamiAgentMemory({ onBack }: { onBack: () => void }) {
  const node = useCurrentNodeId()
  return <MemoryCatalogPage key={node || 'local'} onBack={onBack} />
}

function MemoryCatalogPage({ onBack }: { onBack: () => void }) {
  const { t } = useI18n()
  const { phone } = useLayout()
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([])
  const [failed, setFailed] = useState(false), [version, setVersion] = useState(0)
  useEffect(() => {
    const abort = new AbortController()
    setFailed(false)
    void api('GET', '/projects', undefined, { signal: abort.signal }).then(({ data }) => {
      if (!abort.signal.aborted) setProjects((data.projects || []).map((project: { key: string; name: string }) => ({ id: project.key, name: project.name || project.key })))
    }).catch(() => { if (!abort.signal.aborted) setFailed(true) })
    return () => abort.abort()
  }, [version])
  return <div className="tt-model-hub-roami">
    {!phone && <div className="tt-pagehead tt-model-hub-detail-head"><BackButton onClick={onBack} /><h2>{t('agent.memoryCenter')}</h2></div>}
    {failed && <p role="alert">{t('agent.memoryProjectsFailed')} <Button onClick={() => setVersion(value => value + 1)}>{t('agent.retry')}</Button></p>}
    <AgentMemory fullPage embedded onBack={onBack} projects={projects} select={(cid, branch, message) => { location.hash = '#/home/' + [cid, branch, message].filter(Boolean).map(encodeURIComponent).join('/') }} />
  </div>
}
