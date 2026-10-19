import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n'
import { nodeApi } from '../cluster/node-url'
import Markdown from '../markdown/Markdown'
import type { TaskArtifact, TaskAttempt } from './agent-task-protocol'

export function taskOutputHref(href: string, artifacts: TaskArtifact[]): string {
  const output = artifacts.find(item => item.metadata?.sourcePath === href)
  if (output) return nodeApi('/agent/artifacts/' + encodeURIComponent(output.id) + '/content')
  if (href.startsWith('/api/')) return nodeApi(href.slice(4))
  if (href.startsWith('/') && !href.startsWith('//')) return nodeApi('/file/raw?path=' + encodeURIComponent(href))
  return href
}

export function TaskResult({ attempt, artifacts, onPreview }: { attempt: TaskAttempt; artifacts: TaskArtifact[]; onPreview?: (id: string) => void }) {
  const { t, locale } = useI18n()
  const code = typeof attempt.result?.summary === 'string' ? attempt.result.summary : ''
  const stderr = typeof attempt.result?.stderr === 'string' ? attempt.result.stderr : ''
  const output = typeof attempt.result?.output === 'string' ? attempt.result.output : ''
  const reason = code === 'MODEL_HTTP_401' ? 'authentication' : ['MODEL_DEADLINE', 'EXECUTION_DEADLINE_OR_INTERRUPTION', 'TASK_BUDGET_EXCEEDED'].includes(code) ? 'deadline' : ['AGENT_STEP_LIMIT'].includes(code) ? 'steps' : ['NATIVE_WORKSPACE_UNAVAILABLE', 'PROJECT_PROVISION_UNAVAILABLE'].includes(code) ? 'workspace' : code.includes('OUTCOME_UNKNOWN') ? 'unknown' : ''
  return <>
    {reason && <p className="agent-task-note" role="status">{t('agent.task.failure.' + reason)}</p>}
    {attempt.startedMs && <small className="agent-muted">{t('agent.task.startedAt', { time: new Date(attempt.startedMs).toLocaleString(locale) })}</small>}
    {attempt.finishedMs && <small className="agent-muted">{t('agent.task.finishedAt', { time: new Date(attempt.finishedMs).toLocaleString(locale) })}</small>}
    {attempt.result?.outcomeKnown === false && <p className="agent-task-note" role="status">{t('agent.task.outcomeUnknown')}</p>}
    {code && <div className="agent-task-report"><Markdown resolveHref={href => taskOutputHref(href, artifacts)} onLinkClick={(href, event) => {
      const artifact = artifacts.find(item => item.metadata?.sourcePath === href)
      if (artifact && onPreview && canPreviewArtifact(artifact)) { event.preventDefault(); onPreview(artifact.id) }
    }}>{code}</Markdown></div>}
    {(stderr || output) && <details className="agent-task-log"><summary>{t('agent.task.executionLog')}</summary><p className="agent-muted">{t('agent.task.logHint')}</p>{output && <pre>{output}</pre>}{stderr && <pre>{stderr}</pre>}</details>}
    {typeof attempt.result?.exitCode === 'number' && <small className="agent-muted">{t('agent.task.exitCode', { code: attempt.result.exitCode })}</small>}
  </>
}

export function TaskArtifactPreview({ artifact }: { artifact: TaskArtifact }) {
  const { t } = useI18n()
  const [text, setText] = useState<string | null>(null), [failed, setFailed] = useState(false), [pdfURL, setPdfURL] = useState('')
  const url = nodeApi('/agent/artifacts/' + encodeURIComponent(artifact.id) + '/content')
  const image = /^image\/(png|jpeg|webp|gif)$/.test(artifact.mimeType), pdf = artifact.mimeType === 'application/pdf'
  useEffect(() => {
    if (image) return
    const controller = new AbortController()
    let objectURL = ''
    setText(null); setFailed(false); setPdfURL('')
    void fetch(url, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('ARTIFACT_UNAVAILABLE')
      if (pdf) {
        const body = await response.blob()
        if (!controller.signal.aborted) { objectURL = URL.createObjectURL(body); setPdfURL(objectURL) }
      } else {
        const body = await response.text()
        if (!controller.signal.aborted) setText(body)
      }
    }).catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => { controller.abort(); if (objectURL) URL.revokeObjectURL(objectURL) }
  }, [url, image, pdf])
  if (image) return failed ? <p role="alert">{t('agent.task.artifactsUnavailable')}</p> : <img className="agent-task-preview" src={url} alt={artifact.name} onError={() => setFailed(true)} />
  if (failed) return <p role="alert">{t('agent.task.artifactsUnavailable')}</p>
  if (pdf && pdfURL) return <iframe className="agent-task-frame" src={pdfURL} title={artifact.name} />
  if (text === null) return <p role="status">{t('common.loading')}</p>
  if (artifact.mimeType === 'text/html') return <iframe className="agent-task-frame" sandbox="" title={artifact.name} srcDoc={'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:; base-uri \'none\'; form-action \'none\'">' + text} />
  return <div className="agent-task-document">{artifact.name.toLowerCase().endsWith('.md') ? <Markdown resolveHref={(href, kind) => kind === 'link' && /^https?:\/\//i.test(href) ? href : '#'}>{text}</Markdown> : <pre>{text}</pre>}</div>
}

export const canPreviewArtifact = (artifact: TaskArtifact) => artifact.sizeBytes <= (artifact.mimeType === 'application/pdf' ? 8 : 1) * 1024 * 1024 && (/^image\/(png|jpeg|webp|gif)$/.test(artifact.mimeType) || artifact.mimeType.startsWith('text/') || ['application/json', 'application/pdf'].includes(artifact.mimeType))
