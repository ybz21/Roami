import { useEffect, useRef, useState } from 'react'
import { Button } from 'antd'
import { useLayout } from '../../../layout'
import { useI18n } from '../../../i18n'
import FileBrowser from '../../files/FileBrowser'
import { FileView } from '../../files/fileview'
import MobileSubPage from '../../MobileSubPage'

export default function OkrProjectFiles({ dir, bundleRoot, active, openRequest }: { dir?: string; bundleRoot?: string; active: boolean; openRequest?: { path: string; nonce: number } }) {
  const { phone } = useLayout()
  const { t } = useI18n()
  const [request, setRequest] = useState<{ path: string; nonce: number; directory?: boolean } | undefined>(openRequest)
  const [file, setFile] = useState<string | null>(null)
  const requestNonce = useRef(0)
  const bundleDir = dir && bundleRoot ? dir.replace(/\/$/, '') + '/' + bundleRoot : undefined
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
  return <div className="okr-files">
    <nav className="okr-files-nav" aria-label={t('okr.fileLocations')}>
      {bundleDir && <Button onClick={() => navigate(bundleDir)}>{t('okr.bundleFiles')}</Button>}
      <Button onClick={() => navigate(dir)}>{t('okr.projectAssets')}</Button>
    </nav>
    {!bundleDir && <p className="okr-muted okr-files-hint">{t('okr.bundleNotSaved')}</p>}
    <div className="okr-files-browser"><FileBrowser dir={bundleDir || dir} active={active && visible} layout={phone ? 'dock' : 'split'} onOpenFile={phone ? setFile : undefined} openRequest={request} /></div>
    {phone && file && <MobileSubPage onBack={() => setFile(null)}>
      <FileView path={file} accent="var(--accent)" inline active={active && visible} onBack={() => setFile(null)} onClose={() => setFile(null)} onOpenPath={setFile} />
    </MobileSubPage>}
  </div>
}
