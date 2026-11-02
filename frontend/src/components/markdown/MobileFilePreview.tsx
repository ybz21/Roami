import { Suspense, useEffect, useState } from 'react'
import { Spin } from 'antd'
import MobileSubPage from '../MobileSubPage'
import { lazyRetry } from '../lazy-retry'
import { useI18n } from '../../i18n'
import type { FileLink } from './file-link'
import { DownloadIcon } from '../files/file-icons'
import type { TaskArtifact } from '../agent/agent-task-protocol'
import { canPreviewArtifact, TaskArtifactPreview } from '../agent/TaskOutput'
import DocumentPreview, { isPdfDocument, isPptxDocument } from '../documents/DocumentPreview'

const FileView = lazyRetry(() => import('../files/fileview/FileView').then((m) => ({ default: m.FileView })))

export default function MobileFilePreview({ link, onBack }: { link: FileLink; onBack: () => void }) {
  const { t } = useI18n()
  const [path, setPath] = useState(link.path)
  const [loading, setLoading] = useState(link.resolvePath)
  const [error, setError] = useState('')
  const [artifact, setArtifact] = useState<TaskArtifact | null>(null)
  const name = artifact?.name || path?.split('/').pop() || link.name
  const directDocument = isPdfDocument(name, '') || isPptxDocument(name, '')
  useEffect(() => {
    if (!link.metadataUrl) return
    const controller = new AbortController()
    setLoading(true); setError(''); setArtifact(null)
    void fetch(link.metadataUrl, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error(String(response.status))
      const result = await response.json()
      if (!controller.signal.aborted) setArtifact(result.data)
    }).catch(error => { if (!controller.signal.aborted) setError(String(error)) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [link])
  useEffect(() => {
    if (!link.resolvePath) return
    const controller = new AbortController()
    // Let the server resolve relative aliases before choosing the Markdown/media viewer.
    void fetch(link.url, { method: 'HEAD', cache: 'no-store', credentials: 'same-origin', signal: controller.signal }).then((response) => {
      if (!response.ok) throw new Error(String(response.status))
      const canonical = response.headers.get('X-Roami-File-Path')
      if (canonical) setPath(decodeURIComponent(canonical))
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(String(err))
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [link])
  return (
    <MobileSubPage title={name} onBack={onBack} layer="session"
      action={artifact || directDocument ? { label: t('file.download'), icon: <DownloadIcon />, href: link.url + (link.url.includes('?') ? '&' : '?') + 'dl=1', download: name } : undefined}>
      {loading ? <Spin /> : error ? <div role="alert" style={{ padding: 'var(--sp-4)', color: 'var(--text-dim)' }}>{t('file.openFailed', { message: error })}</div>
        : artifact ? canPreviewArtifact(artifact) ? <TaskArtifactPreview artifact={artifact} contentUrl={link.url} fullHeight /> : <p role="status">{t('document.previewUnavailable')}</p>
        : directDocument ? <div className="document-preview-full"><DocumentPreview src={link.url} name={name} mimeType="" /></div>
        : path ? <Suspense fallback={<Spin />}><FileView path={path} accent="var(--accent)" inline tabbed forcePreview onClose={onBack} onOpenPath={setPath} /></Suspense>
        : <iframe title={link.name} src={link.url} style={{ flex: 1, minHeight: 0, width: '100%', border: 0, background: 'var(--bg-base)' }} />}
    </MobileSubPage>
  )
}
