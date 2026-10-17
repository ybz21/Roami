import { Suspense, useEffect, useState } from 'react'
import { Spin } from 'antd'
import MobileSubPage from '../MobileSubPage'
import { lazyRetry } from '../lazy-retry'
import { useI18n } from '../../i18n'
import type { FileLink } from './file-link'

const FileView = lazyRetry(() => import('../files/fileview/FileView').then((m) => ({ default: m.FileView })))

export default function MobileFilePreview({ link, onBack }: { link: FileLink; onBack: () => void }) {
  const { t } = useI18n()
  const [path, setPath] = useState(link.path)
  const [loading, setLoading] = useState(link.resolvePath)
  const [error, setError] = useState('')
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
    <MobileSubPage title={path?.split('/').pop() || link.name} onBack={onBack} layer="session">
      {loading ? <Spin /> : error ? <div role="alert" style={{ padding: 'var(--sp-4)', color: 'var(--text-dim)' }}>{t('file.openFailed', { message: error })}</div> : path
        ? <Suspense fallback={<Spin />}><FileView path={path} accent="var(--accent)" inline tabbed forcePreview onClose={onBack} onOpenPath={setPath} /></Suspense>
        : <iframe title={link.name} src={link.url} style={{ flex: 1, minHeight: 0, width: '100%', border: 0, background: 'var(--bg-base)' }} />}
    </MobileSubPage>
  )
}
