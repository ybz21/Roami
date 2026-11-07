import { api } from '../../api'
import AgentQuestion from './AgentQuestion'
import AgentReplyPreview from './AgentReplyPreview'
import { memo, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Image } from 'antd'
import { FileTextIcon, NotebookIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { agentResourceUrl } from './agent-resource-url'
import { ChatMessage } from '../chat/Message'
import type { Msg } from '../chat/types'
import type { AgentMessage } from './agent-protocol'
import { activityReason } from './AgentActivity'
import { taskFailureKey } from './task-failure'
import { useLayout } from '../../layout'
import { lazyRetry } from '../lazy-retry'
import { fileLink, type FileLink } from '../markdown/file-link'
import { canPreviewArtifact } from './TaskOutput'

const MobileFilePreview = lazyRetry(() => import('../markdown/MobileFilePreview'))

type Attachment = NonNullable<AgentMessage['content']['attachments']>[number]

const attachmentUrl = (file: Attachment, node: string | null) => agentResourceUrl('/api/agent/artifacts/' + encodeURIComponent(file.id) + '/content', node)

// 图片附件渲染成缩略图：气泡里直接看得见图，点开走 antd preview 全屏放大。
// antd 的 preview 挂在一张隐藏图上、由缩略图受控打开 —— 整张缩略图都是热区，
// 手指落在哪儿都点得中。取不到图就退回原来的文件卡片（可下载），不丢入口。
function AgentImageAttachment({ file, node }: { file: Attachment; node: string | null }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [broken, setBroken] = useState(false)
  const url = attachmentUrl(file, node)
  if (broken) {
    return <a className="agent-file-card" href={url} download={file.name}><FileTextIcon size={20} /><span>{file.name}</span></a>
  }
  return <span className="agent-image-attachment">
    <Image
      src={url}
      alt={file.name}
      style={{ display: 'none' }}
      preview={{ visible: open, src: url, onVisibleChange: setOpen }}
    />
    <button type="button" className="agent-image-thumb" aria-label={`${t('chat.viewImage')} ${file.name}`} onClick={() => setOpen(true)}>
      <img src={url} alt={file.name} loading="lazy" onError={() => setBroken(true)} />
    </button>
  </span>
}

function AgentMessageView({ item: source, node, focused, remember, canAnswer = false, answer, readOnly = false, conversationId, branchId, transformText }: { transformText?: (text: string, content?: AgentMessage['content']) => string; conversationId?: string; branchId?: string; item: AgentMessage; node: string | null; focused: boolean; readOnly?: boolean; remember: (item: AgentMessage) => void; canAnswer?: boolean; answer?: (text: string) => Promise<boolean> }) {
  const { t, locale } = useI18n()
  const { phone } = useLayout()
  const [preview, setPreview] = useState<FileLink | null>(null)
  const [full, setFull] = useState<AgentMessage | null>(null), [loading, setLoading] = useState(false), [failed, setFailed] = useState(false)
  const request = useRef<AbortController | null>(null)
  useEffect(() => { setFull(null); setFailed(false); setLoading(false); return () => request.current?.abort() }, [source.id, source.status, node, conversationId, branchId])
  const raw = full?.id === source.id ? { ...source, ...full, status: source.status } : source
  const item = transformText && raw.role === 'user' && raw.content.text ? { ...raw, content: { ...raw.content, text: transformText(raw.content.text, raw.content) } } : raw
  const readFull = async () => {
    if (!conversationId || loading) return
    const controller = new AbortController(); request.current = controller
    setLoading(true); setFailed(false)
    try {
      const { data } = await api('GET', `/agent/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(source.id)}${branchId ? '?branch=' + encodeURIComponent(branchId) : ''}`, undefined, { signal: controller.signal })
      if (!controller.signal.aborted) setFull(data)
    } catch { if (!controller.signal.aborted) setFailed(true) } finally { if (!controller.signal.aborted) setLoading(false) }
  }
  const assistant = item.role === 'assistant'
  const resolveResource = useCallback((href: string) => agentResourceUrl(href, node), [node])
  const report = item.content.sessionReply
  const reportError = item.content.taskStatus?.reportError
  const reportFailure = taskFailureKey(reportError)
  const reportStatus = report && ['progress', 'blocked', 'completed', 'failed'].includes(report.status) ? report.status : 'unknown'
  const transcript = useMemo<Msg>(() => ({ id: item.id, role: item.role, blocks: item.content.text ? [{ kind: 'text', text: item.content.text }] : [], ...(item.created_ms ? { ts: new Date(item.created_ms).toISOString() } : {}) }), [item.id, item.role, item.content.text, item.created_ms])
  const rememberAction = !readOnly && !item.contentTruncated && assistant && item.status === 'completed' && item.content.text && !item.content.tool_calls?.length ? <button type="button" className="agent-message-action" aria-label={t('agent.remember')} onClick={() => remember(item)}><NotebookIcon size={16} /></button> : undefined
  return <article data-message-id={item.id} data-notification-focus={focused || undefined} className={`agent-message ${item.role}`}>
    {assistant && item.status === 'streaming' && !item.content.replyPreview && <span className="agent-typing" aria-label={t('agent.responding')} />}
    {item.content.replyPreview && <AgentReplyPreview value={item.content.replyPreview} messageId={item.id} resolveResource={resolveResource} />}
    {report && <div className="agent-session-reply" role="status"><strong>{t('agent.sessionReply.' + reportStatus)}</strong><code>{report.sessionId}</code><small>{t('agent.sessionReply.unverified')}</small></div>}
    {item.content.text && <ChatMessage m={transcript} results={{}} side="native" resolveHref={resolveResource} footerActions={rememberAction} />}
    {item.contentTruncated && conversationId && <button type="button" className="tt-act" disabled={loading} onClick={() => { void readFull() }}>{t(loading ? 'agent.pagination.loading' : failed ? 'agent.retry' : 'agent.pagination.fullMessage')}</button>}
    {failed && <p role="alert">{t('agent.requestFailed')}</p>}
    {item.content.question && <AgentQuestion question={item.content.question} disabled={!canAnswer || item.contentTruncated} answer={answer && (text => answer(report ? t('agent.sessionReply.answer', { sessionId: report.sessionId, dispatchId: report.dispatchId, answer: text }) : text))} />}
    {item.content.taskStatus && <div className="agent-task-status" data-state={item.content.taskStatus.state} role="status"><strong>{t('agent.activity.result', { state: t('agent.state.' + item.content.taskStatus.state) })}</strong><span>{item.content.taskStatus.errorCode ? activityReason(item.content.taskStatus.errorCode, t) : t('agent.activity.resultRecorded')}</span><small>{reportError ? t('agent.activity.reportUnavailableReason', { reason: reportFailure ? t(reportFailure) : activityReason(reportError, t) }) : t('agent.activity.reportUnavailable')}</small></div>}
    {!!item.content.attachments?.length && <div className="agent-message-files">{item.content.attachments.map(file => file.mimeType?.startsWith('image/') && file.previewState !== 'unavailable'
      ? <AgentImageAttachment key={file.id} file={file} node={node} />
      : <a key={file.id} className="agent-file-card" href={attachmentUrl(file, node)} download={file.name} onClick={event => {
        if (!phone || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || !canPreviewArtifact(file)) return
        const link = fileLink(attachmentUrl(file, node), location.origin, '/api/file/raw')
        if (link) { event.preventDefault(); setPreview(link) }
      }}><FileTextIcon size={20} /><span>{file.name}<small>{new Intl.NumberFormat(locale, { style: 'unit', unit: file.sizeBytes < 1024 ? 'byte' : 'kilobyte', unitDisplay: 'short', maximumFractionDigits: 1 }).format(file.sizeBytes / (file.sizeBytes < 1024 ? 1 : 1024))}</small></span></a>)}</div>}
    {['failed', 'interrupted'].includes(item.status) && <small className="agent-muted">{t('agent.interrupted')}</small>}
    {assistant && item.completedEventId && <span className="agent-read-sentinel" data-event-id={item.completedEventId} aria-hidden />}
    {preview && <Suspense fallback={null}><MobileFilePreview link={preview} onBack={() => setPreview(null)} /></Suspense>}
  </article>
}

export default memo(AgentMessageView)
