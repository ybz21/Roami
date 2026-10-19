import { useEffect, useState } from 'react'
import { Button } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useCurrentNodeId } from '../cluster/node-url'
import AgentMemory from '../agent/AgentMemory'

export function AgentMemorySettings() {
  const node = useCurrentNodeId()
  return <MemoryCatalogPage key={node || 'local'} />
}

function MemoryCatalogPage() {
  const { t } = useI18n()
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
  return <>
    {failed && <p role="alert">{t('agent.memoryProjectsFailed')} <Button onClick={() => setVersion(value => value + 1)}>{t('agent.retry')}</Button></p>}
    <AgentMemory fullPage projects={projects} select={(cid, branch, message) => { location.hash = '#/home/' + [cid, branch, message].filter(Boolean).map(encodeURIComponent).join('/') }} />
  </>
}
