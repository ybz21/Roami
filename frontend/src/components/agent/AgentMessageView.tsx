import AgentQuestion from './AgentQuestion'
import { useState } from 'react'
import { App, Image } from 'antd'
import { CheckIcon, CopyIcon, FileTextIcon, NotebookIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { nodeApi } from '../cluster/node-url'
import Markdown from '../markdown/Markdown'
import type { AgentMessage } from './agent-protocol'
import { activityReason } from './AgentActivity'

type Attachment = NonNullable<AgentMessage['content']['attachments']>[number]

const attachmentUrl = (file: Attachment) => nodeApi('/agent/artifacts/' + encodeURIComponent(file.id) + '/content')

// 图片附件渲染成缩略图：气泡里直接看得见图，点开走 antd preview 全屏放大。
// antd 的 preview 挂在一张隐藏图上、由缩略图受控打开 —— 整张缩略图都是热区，
// 手指落在哪儿都点得中。取不到图就退回原来的文件卡片（可下载），不丢入口。
function AgentImageAttachment({ file }: { file: Attachment }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [broken, setBroken] = useState(false)
  const url = attachmentUrl(file)
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

export default function AgentMessageView({ item, focused, remember, canAnswer = false, answer }: { item: AgentMessage; focused: boolean; remember: (item: AgentMessage) => void; canAnswer?: boolean; answer?: (text: string) => Promise<boolean> }) {
  const { t, locale } = useI18n(), { message } = App.useApp(), [copied, setCopied] = useState(false)
  const assistant = item.role === 'assistant'
  const report = item.content.sessionReply
  const reportStatus = report && ['progress', 'blocked', 'completed', 'failed'].includes(report.status) ? report.status : 'unknown'
  const copy = async () => {
    try { await navigator.clipboard.writeText(item.content.text || ''); setCopied(true); setTimeout(() => setCopied(false), 1500) }
    catch { message.error(t('agent.composer.copyFailed')) }
  }
  return <article data-message-id={item.id} data-notification-focus={focused || undefined} className={`agent-message ${item.role}`}>
    {assistant && <div className="agent-author">Roami{item.status === 'streaming' && <span className="agent-typing" aria-label={t('agent.responding')} />}</div>}
    {report && <div className="agent-session-reply" role="status"><strong>{t('agent.sessionReply.' + reportStatus)}</strong><code>{report.sessionId}</code><small>{t('agent.sessionReply.unverified')}</small></div>}
    {item.content.text && (assistant ? <Markdown>{item.content.text}</Markdown> : <p className="agent-user-text">{item.content.text}</p>)}
    {item.content.question && <AgentQuestion question={item.content.question} disabled={!canAnswer} answer={answer && (text => answer(report ? t('agent.sessionReply.answer', { sessionId: report.sessionId, dispatchId: report.dispatchId, answer: text }) : text))} />}
    {item.content.taskStatus && <div className="agent-task-status" role="status"><strong>{t('agent.activity.result', { state: t('agent.state.' + item.content.taskStatus.state) })}</strong><span>{item.content.taskStatus.errorCode ? activityReason(item.content.taskStatus.errorCode, t) : t('agent.activity.resultRecorded')}</span><small>{t('agent.activity.reportUnavailable')}</small><code>{item.content.taskStatus.taskId}</code></div>}
    {!!item.content.attachments?.length && <div className="agent-message-files">{item.content.attachments.map(file => file.mimeType?.startsWith('image/') && file.previewState !== 'unavailable'
      ? <AgentImageAttachment key={file.id} file={file} />
      : <a key={file.id} className="agent-file-card" href={nodeApi('/agent/artifacts/' + encodeURIComponent(file.id) + '/content')} download={file.name}><FileTextIcon size={20} /><span>{file.name}<small>{new Intl.NumberFormat(locale, { style: 'unit', unit: file.sizeBytes < 1024 ? 'byte' : 'kilobyte', unitDisplay: 'short', maximumFractionDigits: 1 }).format(file.sizeBytes / (file.sizeBytes < 1024 ? 1 : 1024))}</small></span></a>)}</div>}
    {['failed', 'interrupted'].includes(item.status) && <small className="agent-muted">{t('agent.interrupted')}</small>}
    {assistant && item.status === 'completed' && item.content.text && !item.content.tool_calls?.length && <div className="agent-message-actions"><button type="button" className="agent-message-action" aria-label={t(copied ? 'agent.composer.copied' : 'agent.composer.copy')} onClick={() => { void copy() }}>{copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />}</button><button type="button" className="agent-message-action" aria-label={t('agent.remember')} onClick={() => remember(item)}><NotebookIcon size={16} /></button></div>}
    {assistant && item.completedEventId && <span className="agent-read-sentinel" data-event-id={item.completedEventId} aria-hidden />}
  </article>
}
