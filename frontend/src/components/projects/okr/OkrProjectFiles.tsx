import { useEffect, useRef, useState } from 'react'
import { Button } from 'antd'
import { useLayout } from '../../../layout'
import { useI18n } from '../../../i18n'
import { api } from '../../../api'
import FileBrowser from '../../files/FileBrowser'
import { FileView } from '../../files/fileview'
import MobileSubPage from '../../MobileSubPage'

export default function OkrProjectFiles({ dir, bundleRoot, active, openRequest }: { dir?: string; bundleRoot?: string; active: boolean; openRequest?: { path: string; nonce: number } }) {
  const { phone } = useLayout()
  const { t } = useI18n()
  const [request, setRequest] = useState<{ path: string; nonce: number; directory?: boolean } | undefined>(openRequest)
  const [file, setFile] = useState<string | null>(null)
  const requestNonce = useRef(0)
  const [directories, setDirectories] = useState<string[]>([])
  const bundleDir = dir && bundleRoot ? dir.replace(/\/$/, '') + '/' + bundleRoot : undefined
  useEffect(() => {
    if (!active || !dir || !bundleDir) return
    const controller = new AbortController()
    void api('GET', '/files?path=' + encodeURIComponent(dir), undefined, { signal: controller.signal }).then(response => {
      if (!controller.signal.aborted && Array.isArray(response.data?.entries)) setDirectories(response.data.entries.filter((entry: { name: string; dir: boolean }) => entry.dir && (/^\d{4}$/.test(entry.name) || entry.name === 'archive')).map((entry: { name: string }) => entry.name).sort().reverse())
    }).catch(() => {})
    return () => controller.abort()
  }, [active, dir, bundleDir])
  useEffect(() => { if (openRequest) setRequest(openRequest) }, [openRequest])
  const navigate = (path: string) => {
    setFile(null)
    setRequest({ path, nonce: --requestNonce.current, directory: true })
  }
  const [visible, setVisible] = useState(() => !document.hidden)
  useEffect(() => {
    const update = () => setVisible(!document.hidden)
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  if (!dir) return <p className="okr-muted">{t('okr.filesUnavailable')}</p>
  const root = dir.replace(/\/$/, '')
  const locations = [
    ...(bundleDir ? [
      { path: bundleDir, label: t('okr.bundleFiles') },
      { path: bundleDir + '/agents', label: t('okr.fileTeam') },
      { path: bundleDir + '/memory', label: t('okr.fileMemory') },
      { path: bundleDir + '/connectors', label: t('okr.fileConnectors') },
    ] : []),
    ...directories.map(name => ({ path: root + '/' + name, label: name === 'archive' ? t('okr.fileHistory') : t('okr.fileDaily', { year: name }) })),
    { path: dir, label: t('okr.projectAssets') },
  ]
  const current = [...locations].sort((a, b) => b.path.length - a.path.length).find(item => (request?.path || bundleDir || dir) === item.path || (request?.path || bundleDir || dir).startsWith(item.path + '/'))
  return <div className="okr-files">
    <nav className="okr-files-nav" aria-label={t('okr.fileLocations')}>
      {locations.map(item => <Button key={item.path} aria-label={item.label} aria-pressed={current?.path === item.path} onClick={() => navigate(item.path)}>{item.label}</Button>)}
    </nav>
    {!bundleDir && <p className="okr-muted okr-files-hint">{t('okr.bundleNotSaved')}</p>}
    <div className="okr-files-browser"><FileBrowser dir={bundleDir || dir} active={active && visible} chrome="tree" autoFocusSearch={false} collapseEmptyPreview layout={phone ? 'dock' : 'split'} onOpenFile={phone ? setFile : undefined} openRequest={request} /></div>
    {phone && file && <MobileSubPage onBack={() => setFile(null)}>
      <FileView path={file} accent="var(--accent)" inline active={active && visible} onBack={() => setFile(null)} onClose={() => setFile(null)} onOpenPath={setFile} />
    </MobileSubPage>}
  </div>
}
