import { memo, useEffect, useState } from 'react'
import { useI18n } from '../../i18n'
import { nodeApi } from '../cluster/node-url'
import Markdown from '../markdown/Markdown'
import type { TaskArtifact, TaskAttempt } from './agent-task-protocol'
import { taskFailureKey } from './task-failure'
import DocumentPreview, { isPdfDocument, isPptxDocument } from '../documents/DocumentPreview'

export function taskOutputArtifact(href: string, artifacts: TaskArtifact[], runId?: string): TaskArtifact | undefined {
  return artifacts.find(item => (!runId || !item.metadata?.runId || item.metadata.runId === runId) && (item.metadata?.sourcePath === href || item.metadata?.reportedAliases?.includes(href)))
}

export function taskOutputHref(href: string, artifacts: TaskArtifact[], runId?: string): string {
  const output = taskOutputArtifact(href, artifacts, runId)
  if (output) return nodeApi('/agent/artifacts/' + encodeURIComponent(output.id) + '/content')
  if (href.startsWith('/api/')) return nodeApi(href.slice(4))
  if (href.startsWith('/') && !href.startsWith('//')) return nodeApi('/file/raw?path=' + encodeURIComponent(href))
  return href
}

function TaskResultBody({ attempt, artifacts, onPreview }: { attempt: TaskAttempt; artifacts: TaskArtifact[]; onPreview?: (id: string) => void }) {
  const { t, locale } = useI18n()
  const reported = !attempt.result?.summary && attempt.progress?.source === 'provider_transcript' ? attempt.progress.summary : ''
  const code = typeof attempt.result?.summary === 'string' ? attempt.result.summary : reported
  const stderr = typeof attempt.result?.stderr === 'string' ? attempt.result.stderr : ''
  const output = typeof attempt.result?.output === 'string' ? attempt.result.output : ''
  const reason = attempt.state === 'failed' || attempt.state === 'interrupted' || attempt.result?.outcomeKnown === false ? taskFailureKey(code) : undefined
  return <>
    {reported && <p className="agent-task-note" role="status">{t('agent.task.reportUnconfirmed')}</p>}
    {reason && <p className="agent-task-note" role="status">{t(reason)}</p>}
    {attempt.startedMs && <small className="agent-muted">{t('agent.task.startedAt', { time: new Date(attempt.startedMs).toLocaleString(locale) })}</small>}
    {attempt.finishedMs && <small className="agent-muted">{t('agent.task.finishedAt', { time: new Date(attempt.finishedMs).toLocaleString(locale) })}</small>}
    {attempt.result?.outcomeKnown === false && <p className="agent-task-note" role="status">{t('agent.task.outcomeUnknown')}</p>}
    {code && <div className="agent-task-report"><Markdown resolveHref={href => taskOutputHref(href, artifacts, attempt.id)} onLinkClick={(href, event) => {
      const artifact = taskOutputArtifact(href, artifacts, attempt.id)
      if (artifact && onPreview && canPreviewArtifact(artifact)) { event.preventDefault(); onPreview(artifact.id) }
    }}>{code}</Markdown></div>}
    {(stderr || output) && <details className="agent-task-log"><summary>{t('agent.task.executionLog')}</summary><p className="agent-muted">{t('agent.task.logHint')}</p>{output && <pre>{output}</pre>}{stderr && <pre>{stderr}</pre>}</details>}
    {typeof attempt.result?.exitCode === 'number' && <small className="agent-muted">{t('agent.task.exitCode', { code: attempt.result.exitCode })}</small>}
  </>
}

export const TaskResult = memo(TaskResultBody)

export function TaskArtifactPreview({ artifact, contentUrl, fullHeight = false }: { artifact: TaskArtifact; contentUrl?: string; fullHeight?: boolean }) {
  const { t } = useI18n()
  const [text, setText] = useState<string | null>(null), [failed, setFailed] = useState(false)
  const url = contentUrl || nodeApi('/agent/artifacts/' + encodeURIComponent(artifact.id) + '/content')
  const image = /^image\/(png|jpeg|webp|gif)$/.test(artifact.mimeType)
  const document = isPdfDocument(artifact.name, artifact.mimeType) || isPptxDocument(artifact.name, artifact.mimeType)
  useEffect(() => {
    if (image || document) return
    const controller = new AbortController()
    setText(null); setFailed(false)
    void fetch(url, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('ARTIFACT_UNAVAILABLE')
      const body = await response.text()
      if (!controller.signal.aborted) setText(body)
    }).catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => controller.abort()
  }, [url, image, document])
  if (document) return <div className={fullHeight ? 'document-preview-full' : 'agent-task-document-preview'}><DocumentPreview src={url} name={artifact.name} mimeType={artifact.mimeType} /></div>
  if (image) return failed ? <p role="alert">{t('agent.task.artifactsUnavailable')}</p> : <img className="agent-task-preview" src={url} alt={artifact.name} onError={() => setFailed(true)} />
  if (failed) return <p role="alert">{t('agent.task.artifactsUnavailable')}</p>
  if (text === null) return <p role="status">{t('common.loading')}</p>
  if (artifact.mimeType === 'text/html') return <iframe className="agent-task-frame" sandbox="" title={artifact.name} srcDoc={'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:; base-uri \'none\'; form-action \'none\'">' + text} />
  return <div className="agent-task-document">{artifact.name.toLowerCase().endsWith('.md') ? <Markdown resolveHref={(href, kind) => kind === 'link' && /^https?:\/\//i.test(href) ? href : '#'}>{text}</Markdown> : <pre>{text}</pre>}</div>
}

export const canPreviewArtifact = (artifact: TaskArtifact) => {
  const mime = artifact.mimeType || ''
  const document = isPdfDocument(artifact.name, mime) || isPptxDocument(artifact.name, mime)
  return artifact.sizeBytes <= (document ? 8 : 1) * 1024 * 1024 && (document || /^image\/(png|jpeg|webp|gif)$/.test(mime) || mime.startsWith('text/') || mime === 'application/json')
}
