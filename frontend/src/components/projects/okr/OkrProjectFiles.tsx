import { useEffect, useState } from 'react'
import { useLayout } from '../../../layout'
import { useI18n } from '../../../i18n'
import FileBrowser from '../../files/FileBrowser'
import { FileView } from '../../files/fileview'
import MobileSubPage from '../../MobileSubPage'

export default function OkrProjectFiles({ dir, active, openRequest }: { dir?: string; active: boolean; openRequest?: { path: string; nonce: number } }) {
  const { phone } = useLayout()
  const { t } = useI18n()
  const [file, setFile] = useState<string | null>(null)
  const [visible, setVisible] = useState(() => !document.hidden)
  useEffect(() => {
    const update = () => setVisible(!document.hidden)
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  if (!dir) return <p className="okr-muted">{t('okr.filesUnavailable')}</p>
  return <div className="okr-files">
    <FileBrowser key={dir} dir={dir} active={active && visible} layout={phone ? 'dock' : 'split'} onOpenFile={phone ? setFile : undefined} openRequest={openRequest} />
    {phone && file && <MobileSubPage onBack={() => setFile(null)}>
      <FileView path={file} accent="var(--accent)" inline active={active && visible} onBack={() => setFile(null)} onClose={() => setFile(null)} onOpenPath={setFile} />
    </MobileSubPage>}
  </div>
}
