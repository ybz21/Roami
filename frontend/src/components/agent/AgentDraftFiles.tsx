import { Spin } from 'antd'
import { CloseIcon, FileTextIcon, RefreshIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { useAgentAttachments } from './useAgentAttachments'
import './agent-chat.css'

export default function AgentDraftFiles({ attachments, disabled, imagesAvailable, onError }: { attachments: ReturnType<typeof useAgentAttachments>; disabled: boolean; imagesAvailable: boolean; onError: () => void }) {
  const { t } = useI18n()
  if (!attachments.items.length) return null
  return <div className="agent-draft-files">{attachments.items.map(item => <div className={`agent-file-card is-${item.state}`} key={item.key}>
    <FileTextIcon size={20} /><span>{item.name}<small>{t(item.state === 'uploading' ? item.processing ? 'agent.composer.imagePreparing' : 'agent.composer.uploading' : item.state === 'failed' ? item.preparationFailed ? 'agent.composer.imagePrepareFailed' : 'agent.composer.uploadFailed' : item.reference?.previewState === 'unsupported' ? 'agent.composer.fileStoredOnly' : item.reference?.previewState === 'image' && !imagesAvailable ? 'agent.composer.imageUnavailable' : ['unavailable', 'encrypted', 'no_text'].includes(item.reference?.previewState || '') ? 'agent.composer.fileUnavailable' : item.optimized ? 'agent.composer.imageOptimized' : 'agent.composer.fileReady')}</small></span>
    {item.state === 'uploading' ? <Spin size="small" /> : <>{item.state === 'failed' && <button type="button" aria-label={t('agent.retry')} disabled={disabled} onClick={() => { void attachments.retry(item) }}><RefreshIcon size={15} /></button>}<button type="button" aria-label={t('agent.composer.removeFile', { name: item.name })} disabled={disabled} onClick={() => { void attachments.remove(item).catch(onError) }}><CloseIcon size={15} /></button></>}
  </div>)}</div>
}
