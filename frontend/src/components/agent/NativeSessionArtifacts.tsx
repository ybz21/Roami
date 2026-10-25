import { useState } from 'react'
import { Modal } from 'antd'
import { FileTextIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { nodeApi } from '../cluster/node-url'
import MobileSubPage from '../MobileSubPage'
import { TaskArtifactPreview, canPreviewArtifact } from './TaskOutput'
import type { TaskArtifact, TaskDetail } from './agent-task-protocol'
import { taskFailureKey } from './task-failure'
import { taskOutcome, taskReportLinks } from './task-outcome'

export default function NativeSessionArtifacts({ detail, artifacts, failed, retry }: { detail: TaskDetail; artifacts: TaskArtifact[]; failed: boolean; retry: () => void }) {
  const { t, locale } = useI18n(), { phone } = useLayout()
  const [previewId, setPreviewId] = useState('')
  const files = [...new Map([...artifacts, ...(detail.delivery?.artifacts || [])].map(file => [file.id, file])).values()]
  const latest = detail.attempts[0], current = latest?.revision === detail.task.revision ? latest : undefined
  const preview = files.find(file => file.id === previewId)
  const contentUrl = (file: TaskArtifact) => nodeApi('/agent/artifacts/' + encodeURIComponent(file.id) + '/content')
  const download = (file: TaskArtifact) => <a className="tt-act native-artifact-download" href={contentUrl(file) + '?dl=1'} download={file.name} aria-label={t('agent.task.downloadNamed', { name: file.name })}>{t('agent.task.download')}</a>
  const groups = [
    { key: 'current', files: files.filter(file => !!current && file.metadata?.runId === current.id), label: t('agent.task.currentArtifacts') },
    { key: 'history', files: files.filter(file => file.metadata?.runId && file.metadata.runId !== current?.id), label: t('agent.task.previousArtifacts') },
    { key: 'other', files: files.filter(file => !file.metadata?.runId), label: t('agent.task.otherArtifacts') },
  ]
  const failedOutcome = ['failed', 'interrupted'].includes(detail.task.state) || current?.result?.outcomeKnown === false
  const summary = failedOutcome ? t(taskFailureKey(detail.outcome?.errorCode || current?.result?.summary || '') || 'agent.task.incomplete') : taskOutcome(current)
  const links = taskReportLinks(current)
  return <div className="native-session-artifacts">
    {detail.task.state !== 'succeeded' && <p className="agent-task-note" role="status">{t('agent.task.artifactStatus', { state: t('agent.state.' + detail.task.state) })}</p>}
    {summary && <section className="native-artifact-result"><h3>{t('agent.task.result')}</h3><p>{summary}</p></section>}
    {!!links.length && <div className="agent-task-actions">{links.map(href => <a className="tt-act" key={href} href={href} target="_blank" rel="noopener noreferrer">{t('agent.task.openPullRequest', { n: href.split('/').pop()! })}</a>)}</div>}
    {failed && <p role="alert">{t('agent.task.artifactsUnavailable')} <button type="button" className="tt-act" onClick={retry}>{t('agent.retry')}</button></p>}
    {!!detail.delivery?.unavailable.length && <p className="agent-task-note" role="status">{t('agent.task.outputsUnavailable')}<small>{detail.delivery.unavailable.map(item => item.sourcePath).join(' · ')}</small></p>}
    {groups.filter(group => group.files.length).map(group => <section key={group.key} className="native-artifact-group"><h3>{group.label}</h3>{group.files.map(file => {
      const run = detail.attempts.find(attempt => attempt.id === file.metadata?.runId)
      return <div className="native-artifact-row" key={file.id}>
      <FileTextIcon size={20} /><div className="native-artifact-info"><b>{file.name}</b><small><span>{file.name.includes('.') ? file.name.split('.').pop()?.toUpperCase() : file.mimeType}</span><span>{new Intl.NumberFormat(locale, { style: 'unit', unit: file.sizeBytes < 1024 ? 'byte' : 'kilobyte', unitDisplay: 'short', maximumFractionDigits: 1 }).format(file.sizeBytes / (file.sizeBytes < 1024 ? 1 : 1024))}</span>{!!file.createdMs && <time>{new Date(file.createdMs).toLocaleString(locale, { dateStyle: 'short', timeStyle: 'short' })}</time>}</small>{group.key === 'history' && run && <small>{t('agent.task.executionNumber', { n: run.attemptNo ?? run.revision })}</small>}</div>
      <div className="agent-task-actions">{canPreviewArtifact(file) && <button type="button" className="tt-act" aria-label={t('agent.task.previewNamed', { name: file.name })} onClick={() => setPreviewId(file.id)}>{t('agent.task.preview')}</button>}{download(file)}</div>
    </div>})}</section>)}
    {!files.length && !failed && !detail.delivery?.unavailable.length && <p className="agent-muted">{t('agent.task.noArtifacts')}</p>}
    {preview && (phone ? <MobileSubPage title={preview.name} onBack={() => setPreviewId('')} layer="session" search={false}><div className="native-artifact-preview"><div className="native-artifact-preview-actions">{download(preview)}</div><TaskArtifactPreview key={preview.id} artifact={preview} fullHeight /></div></MobileSubPage> : <Modal open title={preview.name} onCancel={() => setPreviewId('')} footer={download(preview)} width="min(90vw, var(--content-form))"><div className="native-artifact-preview"><TaskArtifactPreview key={preview.id} artifact={preview} fullHeight /></div></Modal>)}
  </div>
}
