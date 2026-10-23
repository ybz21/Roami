import { useState } from 'react'
import { Alert, Button, Form, Input, Modal, Segmented, Upload } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { FileTextIcon, UploadIcon, PlugIcon, TerminalIcon } from '../../icons'
import MobileSubPage from '../MobileSubPage'
import Markdown from '../markdown/Markdown'
import { MAX_IMPORT_BYTES, parseCapability, type ManagedEntry, type ManagedKind } from './capability-format'

export function capabilityError(code: string, t: (key: string) => string): string {
  const key = 'capabilities.error.' + code
  const text = t(key)
  return text === key ? t('capabilities.error.failed') : text
}

export default function CapabilityEditor({ kind, entry, draft, importing = false, onClose, onSaved }: {
  kind: ManagedKind; entry?: ManagedEntry; draft?: ManagedEntry; importing?: boolean; onClose: () => void; onSaved: (data: any) => void
}) {
  const initial = entry || draft
  const { t } = useI18n()
  const { phone } = useLayout()
  const [stage, setStage] = useState(importing ? 'upload' : 'edit')
  const [raw, setRaw] = useState('')
  const [fileName, setFileName] = useState('')
  const [name, setName] = useState(initial?.name || '')
  const [description, setDescription] = useState(initial?.description || '')
  const [text, setText] = useState((initial?.text || '').replace(/^---\n[\s\S]*?\n---\n/, ''))
  const [preview, setPreview] = useState(false)
  const [transport, setTransport] = useState(String(initial?.config?.transport || 'streamable_http'))
  const [command, setCommand] = useState(String(initial?.config?.command || initial?.argv?.[0] || ''))
  const [args, setArgs] = useState(JSON.stringify(initial?.config?.args || initial?.argv?.slice(1) || [], null, 2))
  const [url, setUrl] = useState(String(initial?.config?.url || ''))
  const [cwd, setCwd] = useState(initial?.cwd || '')
  const [schema, setSchema] = useState(initial?.schema)
  const [batch, setBatch] = useState<Record<string, unknown> | null>(null)
  const [advanced, setAdvanced] = useState(JSON.stringify(initial?.config ? Object.fromEntries(Object.entries(initial.config).filter(([key]) => !['transport', 'command', 'args', 'url', 'type'].includes(key))) : {}, null, 2))
  const [extras, setExtras] = useState<Partial<ManagedEntry>>({ ...(initial?.origin ? { origin: initial.origin } : {}), ...(initial?.files ? { files: initial.files } : {}), ...(initial?.argumentMode ? { argumentMode: initial.argumentMode } : {}) })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const title = entry ? t('capabilities.editNamed', { name: entry.name }) : t('capabilities.' + (stage === 'upload' ? 'importTitle.' : fileName || raw ? 'reviewTitle.' : 'createTitle.') + kind)
  const report = (caught: any) => setError(capabilityError(caught instanceof SyntaxError ? 'INVALID_CAPABILITY_JSON' : caught.message, t))
  const loadImport = (value = raw) => {
    setError('')
    try {
      const parsed = parseCapability(kind, value) as ManagedEntry & { mcpServers?: Record<string, unknown> }
      setRaw(value)
      if (parsed.mcpServers) {
        if (kind !== 'mcp' || entry || typeof parsed.mcpServers !== 'object' || Array.isArray(parsed.mcpServers) || !Object.keys(parsed.mcpServers).length) throw new Error('INVALID_MCP_CONFIG')
        setBatch(parsed.mcpServers)
      } else {
        if (typeof parsed.name !== 'string' || !parsed.name) throw new Error('INVALID_CAPABILITY_NAME')
        if (parsed.description !== undefined && typeof parsed.description !== 'string') throw new Error('INVALID_CAPABILITY_IMPORT')
        const allowed = kind === 'cli' ? ['name', 'description', 'argv', 'cwd', 'schema', 'argumentMode', 'origin'] : kind === 'mcp' ? ['name', 'config', 'origin'] : ['name', 'description', 'text', 'files', 'origin']
        if (Object.keys(parsed).some(key => !allowed.includes(key))) throw new Error('INVALID_CAPABILITY_IMPORT')
        if (parsed.origin && (typeof parsed.origin !== 'object' || !['source', 'id', 'version', 'url'].every(key => typeof (parsed.origin as Record<string, unknown>)[key] === 'string') || !parsed.origin.url.startsWith('https://'))) throw new Error('INVALID_CAPABILITY_IMPORT')
        if (entry && entry.name !== parsed.name) throw new Error('INVALID_CAPABILITY_NAME')
        setBatch(null); setName(parsed.name); setDescription(parsed.description || '')
        setExtras({ ...(parsed.origin ? { origin: parsed.origin } : {}), ...(parsed.files ? { files: parsed.files } : {}), ...(parsed.argumentMode ? { argumentMode: parsed.argumentMode } : {}) })
        if (kind === 'skills') setText((parsed.text || '').replace(/^---\n[\s\S]*?\n---\n/, ''))
        if (kind === 'cli') {
          if (!Array.isArray(parsed.argv) || !parsed.argv.length || !parsed.argv.every(part => typeof part === 'string')) throw new Error('INVALID_CAPABILITY_IMPORT')
          setCommand(parsed.argv[0]); setArgs(JSON.stringify(parsed.argv.slice(1), null, 2)); setCwd(parsed.cwd || ''); setSchema(parsed.schema)
        }
        if (kind === 'mcp') {
          const config = parsed.config
          if (!config || typeof config !== 'object' || Array.isArray(config)) throw new Error('INVALID_MCP_CONFIG')
          const connection = String(config.transport || (config.type === 'http' ? 'streamable_http' : config.type) || (config.url ? 'streamable_http' : 'stdio'))
          if (!['stdio', 'sse', 'streamable_http'].includes(connection)) throw new Error('INVALID_MCP_CONFIG')
          if (config.type && config.transport && config.transport !== (config.type === 'http' ? 'streamable_http' : config.type)) throw new Error('INVALID_MCP_CONFIG')
          setTransport(connection); setCommand(String(config.command || '')); setArgs(JSON.stringify(config.args || [], null, 2)); setUrl(String(config.url || ''))
          setAdvanced(JSON.stringify(Object.fromEntries(Object.entries(config).filter(([key]) => !['transport', 'command', 'args', 'url', 'type'].includes(key))), null, 2))
        }
      }
      setPreview(false); setStage('edit')
    } catch (caught) { report(caught) }
  }
  const upload = async (file: File) => {
    if (file.size > MAX_IMPORT_BYTES) { setError(t('capabilities.error.CAPABILITY_IMPORT_TOO_LARGE')); return }
    try { const value = await file.text(); setFileName(file.name); setRaw(value); loadImport(value) } catch (caught) { report(caught) }
  }
  const submit = async () => {
    if (stage === 'upload') { loadImport(); return }
    setError(''); setBusy(true)
    try {
      let payload: Record<string, unknown>
      if (batch) payload = parseCapability(kind, raw)
      else if (kind === 'skills') payload = { name: name.trim(), description: description.trim(), text }
      else if (kind === 'cli') payload = { name: name.trim(), description: description.trim(), argv: [command.trim(), ...parseArguments(args)], ...(cwd.trim() ? { cwd: cwd.trim() } : {}), ...(schema ? { schema } : {}) }
      else payload = { name: name.trim(), config: { ...parseAdvanced(advanced), transport, ...(transport === 'stdio' ? { command: command.trim(), args: parseArguments(args) } : { url: url.trim() }) } }
      if (!batch) payload = { ...payload, ...extras }
      if (entry && payload.name !== entry.name) throw new Error('INVALID_CAPABILITY_NAME')
      const path = '/agent/capability-imports/' + kind + (entry ? '/' + encodeURIComponent(entry.name) : '')
      const { data } = await api(entry ? 'PUT' : 'POST', path, payload)
      onSaved(data)
    } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  const template = () => {
    setDescription(description || t('capabilities.template.description')); setText(t('capabilities.template.instructions')); setPreview(false)
  }
  const disabled = stage === 'upload' ? !raw.trim() : batch ? false : !name.trim() || (kind === 'skills' ? !text.trim() : kind === 'mcp' && transport !== 'stdio' ? !url.trim() : !command.trim())
  const content = <Form className="tt-capability-editor" layout="vertical" onFinish={() => { void submit() }}>
    <div className="tt-capability-editor-fields">
      <div className="tt-capability-editor-intro"><span className="tt-capability-editor-mark">{kind === 'skills' ? <FileTextIcon size={24} /> : kind === 'mcp' ? <PlugIcon size={24} /> : <TerminalIcon size={24} />}</span><p>{t('capabilities.editorHint.' + kind)}</p></div>
      {extras.origin && <p className="tt-market-origin">{t('capabilities.market.from', { source: extras.origin.source })}<a href={extras.origin.url} target="_blank" rel="noreferrer">{extras.origin.version.slice(0, 40)}</a></p>}
      {initial?.argumentMode === 'argv' && <Alert type="info" message={t('capabilities.market.cliHint')} />}
      {stage === 'upload' ? <>
        <Upload.Dragger accept={kind === 'skills' ? '.md,text/markdown' : '.json,application/json'} showUploadList={false} disabled={busy} beforeUpload={file => { void upload(file); return false }} className="tt-capability-dropzone">
          <div className="tt-capability-drop-content"><span className="tt-capability-upload-icon"><UploadIcon size={24} /></span>
          <strong>{t('capabilities.dropFile.' + kind)}</strong>
          <span>{t('capabilities.dropHint')}</span></div>
        </Upload.Dragger>
        <details className="tt-capability-paste" open={!!raw}>
          <summary>{t('capabilities.pasteInstead')}</summary>
          <Form.Item label={t(kind === 'skills' ? 'capabilities.skillFile' : 'capabilities.jsonConfig')} extra={t('capabilities.format.' + kind)}>
            <Input.TextArea aria-label={t('capabilities.importContent')} value={raw} onChange={event => { setRaw(event.target.value); setFileName('') }} autoSize={{ minRows: 5, maxRows: 12 }} spellCheck={false} />
          </Form.Item>
        </details>
      </> : <>
        {fileName && <div className="tt-capability-file"><FileTextIcon size={18} /><span><strong>{fileName}</strong><small>{t('capabilities.fileReady')}</small></span><Button type="text" disabled={busy} onClick={() => setStage('upload')}>{t('capabilities.replaceFile')}</Button></div>}
        {batch ? <>
          <Alert type="info" message={t('capabilities.batchPreview', { count: Object.keys(batch).length })} />
          <Form.Item label={t('capabilities.jsonConfig')}><Input.TextArea aria-label={t('capabilities.importContent')} value={raw} onChange={event => setRaw(event.target.value)} autoSize={{ minRows: 8, maxRows: 16 }} /></Form.Item>
        </> : <>
          <div className="tt-capability-identity-fields">
            <Form.Item label={t('capabilities.name')} required extra={t(entry ? 'capabilities.nameFixed' : kind === 'mcp' ? 'capabilities.mcpNameHint' : 'capabilities.nameHint')}><Input maxLength={kind === 'mcp' ? 20 : 64} aria-label={t('capabilities.name')} disabled={!!entry} placeholder={t('capabilities.nameExample.' + kind)} value={name} onChange={event => setName(event.target.value)} autoComplete="off" /></Form.Item>
            {kind !== 'mcp' && <Form.Item label={t('capabilities.description')}><Input aria-label={t('capabilities.description')} placeholder={t('capabilities.descriptionExample')} value={description} onChange={event => setDescription(event.target.value)} /></Form.Item>}
          </div>
          {kind === 'skills' && <div className="tt-capability-instructions">
            <div className="tt-capability-writing-head"><label htmlFor="capability-instructions">{t('capabilities.instructions')}</label><Segmented size="small" value={preview ? 'preview' : 'write'} onChange={value => setPreview(value === 'preview')} options={[{ value: 'write', label: t('capabilities.write') }, { value: 'preview', label: t('capabilities.preview') }]} /></div>
            {preview ? <div className="tt-capability-markdown"><Markdown>{text || t('capabilities.previewEmpty')}</Markdown></div> : <Input.TextArea id="capability-instructions" aria-label={t('capabilities.instructions')} placeholder={t('capabilities.instructionsExample')} value={text} onChange={event => setText(event.target.value)} autoSize={{ minRows: 6, maxRows: 14 }} />}
            {!entry && !text.trim() && <Button className="tt-capability-template" type="link" onClick={template}>{t('capabilities.useTemplate')}</Button>}
          </div>}
          {kind === 'mcp' && <Form.Item label={t('capabilities.transport')}><Segmented block aria-label={t('capabilities.transport')} value={transport} onChange={value => setTransport(String(value))} options={['stdio', 'sse', 'streamable_http'].map(value => ({ value, label: t('capabilities.transport.' + value) }))} /></Form.Item>}
          {kind === 'mcp' && transport !== 'stdio' ? <Form.Item label={t('capabilities.url')} required><Input aria-label={t('capabilities.url')} value={url} onChange={event => setUrl(event.target.value)} placeholder={transport === 'sse' ? 'https://example.com/sse' : 'https://example.com/mcp'} /></Form.Item> : kind !== 'skills' && <>
            <Form.Item label={t('capabilities.command')} required><Input aria-label={t('capabilities.command')} placeholder={kind === 'cli' ? 'python3' : 'npx'} value={command} onChange={event => setCommand(event.target.value)} spellCheck={false} /></Form.Item>
            <Form.Item label={t('capabilities.arguments')} extra={kind === 'cli' ? t('capabilities.argumentsHint') : undefined}><Input.TextArea aria-label={t('capabilities.arguments')} value={args} onChange={event => setArgs(event.target.value)} autoSize={{ minRows: 2, maxRows: 6 }} spellCheck={false} /></Form.Item>
          </>}
          {kind === 'cli' && <Form.Item label={t('capabilities.cwd')} extra={t('capabilities.cwdHint')}><Input aria-label={t('capabilities.cwd')} value={cwd} onChange={event => setCwd(event.target.value)} /></Form.Item>}
          {kind === 'mcp' && <details><summary>{t('capabilities.advanced')}</summary><Form.Item label={t('capabilities.environment')} extra={t('capabilities.environmentHint')}><Input.TextArea aria-label={t('capabilities.environment')} value={advanced} onChange={event => setAdvanced(event.target.value)} autoSize={{ minRows: 4, maxRows: 10 }} spellCheck={false} /></Form.Item></details>}
        </>}
        {!fileName && <div className="tt-capability-import-shortcut"><span>{t('capabilities.haveFile')}</span><Button type="link" icon={<UploadIcon size={16} />} disabled={busy} onClick={() => { setStage('upload'); setError('') }}>{t('capabilities.uploadFile')}</Button></div>}
      </>}
    </div>
    {error && <Alert type="error" showIcon message={error} />}
    <div className="tt-capability-editor-actions"><span className="tt-capability-save-note">{t('capabilities.saveHint')}</span><Button disabled={busy} onClick={onClose}>{t('common.cancel')}</Button><Button type="primary" htmlType="submit" loading={busy} disabled={disabled}>{stage === 'upload' ? t('capabilities.reviewImport') : entry ? t('capabilities.saveChanges') : fileName || raw ? t('capabilities.confirmImport') : t('capabilities.createAction.' + kind)}</Button></div>
  </Form>
  return phone ? <MobileSubPage title={title} search={false} onBack={() => { if (!busy) onClose() }}>{content}</MobileSubPage>
    : <Modal open title={title} footer={null} width="min(var(--content-form), calc(100vw - var(--sp-5) * 2))" closable={!busy} maskClosable={false} keyboard={!busy} onCancel={onClose} className="tt-capability-modal tt-capability-editor-modal">{content}</Modal>
}

function parseArguments(text: string): string[] {
  const value = JSON.parse(text)
  if (!Array.isArray(value) || !value.every(item => typeof item === 'string')) throw new Error('INVALID_CAPABILITY_JSON')
  return value
}
function parseAdvanced(text: string): Record<string, unknown> {
  const value = JSON.parse(text)
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('INVALID_CAPABILITY_JSON')
  return value
}
