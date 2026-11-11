import { BackLink } from '../BackButton'
import { useEffect, useState } from 'react'
import { Spin } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { DownloadIcon, FileTypeIcon } from '../files/file-icons'
import { nodePath } from '../cluster/node-url'
import { TaskArtifactPreview, canPreviewArtifact } from './TaskOutput'
import type { TaskArtifact } from './agent-task-protocol'
import type { readArtifactPreviewRoute } from './artifact-preview-route'

export default function ArtifactPreviewPage({ route }: { route: NonNullable<ReturnType<typeof readArtifactPreviewRoute>> }) {
  // This route runs without AppShell's layout subscription.
  useLayout()
  const { t } = useI18n()
  const [artifact, setArtifact] = useState<TaskArtifact | null>(null), [failed, setFailed] = useState(false), [retry, setRetry] = useState(0)
  const metadataUrl = nodePath('/api/agent/artifacts/' + encodeURIComponent(route.id), route.node)
  const contentUrl = metadataUrl + '/content'
  useEffect(() => {
    const controller = new AbortController()
    setArtifact(null); setFailed(false)
    void fetch(metadataUrl, { signal: controller.signal, cache: 'no-store' }).then(async response => {
      if (!response.ok) throw new Error('ARTIFACT_UNAVAILABLE')
      const result = await response.json()
      if (!result.data?.name || result.data.id !== route.id) throw new Error('ARTIFACT_UNAVAILABLE')
      if (!controller.signal.aborted) setArtifact(result.data)
    }).catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => controller.abort()
  }, [metadataUrl, route.id, retry])
  useEffect(() => {
    const title = document.title
    if (artifact) document.title = artifact.name + ' · Roami'
    return () => { document.title = title }
  }, [artifact])
  return <main className="task-artifact-page">
    <header className="tt-pagehead task-artifact-page-head">
      <BackLink href={route.from} />
      <div className="task-artifact-page-title">{artifact && <span aria-hidden="true"><FileTypeIcon name={artifact.name} /></span>}<h2 title={artifact?.name}>{artifact?.name || t('agent.task.preview')}</h2></div>
      <div className="acts"><a className="tt-act" href={contentUrl + '?dl=1'} download={artifact?.name}><DownloadIcon />{t('agent.task.download')}</a></div>
    </header>
    {failed ? <div className="task-artifact-preview-state" role="alert"><p>{t('document.loadFailed')}</p><button type="button" className="tt-act" onClick={() => setRetry(value => value + 1)}>{t('agent.retry')}</button></div>
      : !artifact ? <div className="task-artifact-preview-state" role="status" aria-label={t('common.loading')}><Spin /></div>
      : canPreviewArtifact(artifact) ? <div className="task-artifact-reader"><TaskArtifactPreview key={artifact.id} artifact={artifact} contentUrl={contentUrl} fullHeight /></div>
      : <div className="task-artifact-preview-state" role="status"><p>{t('document.previewUnavailable')}</p></div>}
  </main>
}
