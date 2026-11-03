import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { DownloadIcon, EyeIcon } from '../files/file-icons'
import { nodeApi } from '../cluster/node-url'
import MobileSubPage from '../MobileSubPage'
import { TaskArtifactPreview } from './TaskOutput'
import type { TaskArtifact } from './agent-task-protocol'
import { artifactPreviewHref } from './artifact-preview-route'

export function TaskArtifactLink({ artifact, onPreview }: { artifact: TaskArtifact; onPreview: (id: string) => void }) {
  const { t } = useI18n(), { phone } = useLayout()
  return <a className="tt-act agent-task-file-preview" href={artifactPreviewHref(artifact.id)} target={phone ? undefined : '_blank'} rel="noopener noreferrer"
    aria-label={t('agent.task.previewNamed', { name: artifact.name })} onClick={event => {
      if (!phone || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
      event.preventDefault(); onPreview(artifact.id)
    }}><EyeIcon />{t('agent.task.preview')}</a>
}

export function TaskArtifactMobilePreview({ artifact, onBack }: { artifact: TaskArtifact; onBack: () => void }) {
  const { t } = useI18n()
  return <MobileSubPage title={artifact.name} onBack={onBack} layer="session" search={false}
    action={{ label: t('agent.task.downloadNamed', { name: artifact.name }), icon: <DownloadIcon />, href: nodeApi('/agent/artifacts/' + encodeURIComponent(artifact.id) + '/content?dl=1'), download: artifact.name }}>
    <div className="task-artifact-reader"><TaskArtifactPreview key={artifact.id} artifact={artifact} fullHeight /></div>
  </MobileSubPage>
}
