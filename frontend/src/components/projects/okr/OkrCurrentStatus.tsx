import { useState } from 'react'
import { Button, Spin } from 'antd'
import { useI18n } from '../../../i18n'
import { openAgentPage } from '../../agent/agent-page-route'
import { artifactPreviewHref } from '../../agent/artifact-preview-route'
import { TaskArtifactLink, TaskArtifactMobilePreview } from '../../agent/TaskArtifactLink'
import type { TaskArtifact } from '../../agent/agent-task-protocol'
import { nodeApi } from '../../cluster/node-url'
import { useSwarmSnapshot } from '../../swarm/useSwarmSnapshot'
import { swarmStateToken, type SwarmWork } from '../../swarm/swarm-protocol'

type EvidenceWork = SwarmWork & { evidence?: { artifacts: { id: string; name: string; mimeType: string; sizeBytes: number }[]; verification?: { state?: string; kind?: string; externalAction?: string | null; receipt?: { artifactId: string; target: string; state: string } } | null } }

export default function OkrCurrentStatus({ swarm, onActivities, onConfigure }: { swarm: string; onActivities: () => void; onConfigure: () => void }) {
  const { t } = useI18n()
  if (!swarm) return <section className="okr-section"><p className="okr-muted">{t('okr.noSwarm')}</p><Button onClick={onConfigure}>{t('okr.changeTeam')}</Button></section>
  return <TeamStatus key={swarm} swarm={swarm} onActivities={onActivities} onConfigure={onConfigure} />
}

function TeamStatus({ swarm, onActivities, onConfigure }: { swarm: string; onActivities: () => void; onConfigure: () => void }) {
  const { t, locale } = useI18n()
  const snapshot = useSwarmSnapshot(swarm)
  const { data, error, refresh } = snapshot
  const missing = !/^sw-[a-f0-9]{32}$/.test(swarm) || 'missing' in snapshot && !!snapshot.missing
  const [preview, setPreview] = useState<TaskArtifact | null>(null)
  if (!data) return <section className="okr-section">{error || missing ? <><p role="alert">{t('okr.statusUnavailable')}</p><p className="okr-muted">{t('okr.linkManagedTeam')}</p><div className="okr-actions"><Button onClick={onActivities}>{t('okr.viewTeamHistory')}</Button><Button onClick={onConfigure}>{t('okr.changeTeam')}</Button>{!missing && <Button onClick={() => void refresh()}>{t('inbox.retry')}</Button>}</div></> : <Spin />}</section>
  return <section className="okr-section">
    <div className="okr-section-head"><h3>{t('okr.teamStatus')}</h3><Button onClick={onActivities}>{t('okr.tab.activities')}</Button></div>
    <div className="okr-status-summary"><strong>{data.name}</strong><span style={{ color: `var(${swarmStateToken(data.state)})` }}>{t('swarm.managed.state.' + data.state)}</span>{data.paused && <span>{t('swarm.managed.paused')}</span>}</div>
    {error && <p role="status" className="okr-muted">{t('swarm.managed.reconnecting')}</p>}
    {data.mainState === 'failed' && <p role="alert">{t('swarm.managed.mainFailed')}</p>}
    {!data.work.length && <p className="okr-muted">{t('okr.noManagedTasks')}</p>}
    <div className="okr-status-grid">{data.work.map((item: EvidenceWork) => <article key={item.id} className="okr-status-task">
      <div className="okr-section-head"><h4>{item.title}</h4><span className="okr-task-state" style={{ color: `var(${swarmStateToken(item.state)})` }}>{t('swarm.managed.state.' + item.state)}</span></div>
      <p className="okr-muted">{item.member_name}</p>
      <section><h4>{t('okr.taskDeliverables')}</h4>
        {item.evidence?.artifacts.length ? item.evidence.artifacts.map(artifact => {
          const url = nodeApi('/agent/artifacts/' + encodeURIComponent(artifact.id) + '/content')
          const media = /^(video|audio)\//.test(artifact.mimeType)
          return <div key={artifact.id}><div className="okr-deliverable"><div>{artifact.name}<p className="okr-muted">{t('okr.artifactSize', { size: new Intl.NumberFormat(locale).format(artifact.sizeBytes) })}</p></div>{media ? <a className="tt-act" href={url + '?dl=1'} download={artifact.name} aria-label={t('agent.task.downloadNamed', { name: artifact.name })}>{t('agent.task.download')}</a> : <TaskArtifactLink artifact={artifact} onPreview={() => setPreview(artifact)} />}</div>
            {artifact.mimeType.startsWith('video/') && <video className="okr-task-media" controls playsInline preload="metadata" src={url} aria-label={artifact.name} />}
            {artifact.mimeType.startsWith('audio/') && <audio className="okr-task-media" controls preload="metadata" src={url} aria-label={artifact.name} />}
          </div>
        }) : <p className="okr-muted">{t('okr.noTaskEvidence')}</p>}
        <p className="okr-muted">{t(!item.evidence?.verification ? 'okr.verificationUnknown' : ['missing', 'awaiting_acceptance', 'accepted'].includes(item.evidence.verification.state || '') ? 'okr.verification.' + item.evidence.verification.state : 'okr.verificationRecorded')}</p>
        {item.evidence?.verification?.externalAction && <p className="okr-muted">{t(item.evidence.verification.externalAction === 'confirmed' ? 'okr.externalConfirmed' : 'okr.externalUnconfirmed')}</p>}
        {item.evidence?.verification?.receipt && <a className="okr-deliverable" target="_blank" rel="noopener noreferrer" href={artifactPreviewHref(item.evidence.verification.receipt.artifactId)}>{t('okr.externalReceipt', { target: item.evidence.verification.receipt.target })}</a>}
      </section>
      {item.dispatch_error && <p role="alert">{t(item.dispatch_error === 'SWARM_DEPENDENCY_NOT_VERIFIED' ? 'swarm.managed.dependencyBlocked' : 'swarm.managed.dispatchFailed')}</p>}
      {item.dependencies.length > 0 && <details><summary>{t('swarm.managed.dependencies')}</summary>{item.dependencies.map(dependency => <p key={dependency.upstreamId}>{data.work.find(work => work.id === dependency.upstreamId)?.title || t('okr.unknownDependency')}</p>)}</details>}
      {item.attempt?.summary && <details><summary>{t('okr.executorReport')}</summary><p>{item.attempt.summary}</p></details>}
      {item.task_id && <Button onClick={() => openAgentPage('tasks', item.task_id!)}>{t('swarm.managed.openTask')}</Button>}
    </article>)}</div>
    {preview && <TaskArtifactMobilePreview artifact={preview} onBack={() => setPreview(null)} />}
  </section>
}
