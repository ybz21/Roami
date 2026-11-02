import { useState } from 'react'
import { Alert, Button, Form, Input, Modal, Select, Switch } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import MobileSubPage from '../MobileSubPage'
import { capabilityError } from './CapabilityEditor'

export type MarketSource = { id: string; name: string; provider: 'skills_sh' | 'mcp_registry' | 'npm'; url: string; enabled: boolean }

export default function MarketSources({ sources, onClose, onSaved }: { sources: MarketSource[]; onClose: () => void; onSaved: (sources: MarketSource[]) => void }) {
  const { t } = useI18n()
  const { phone } = useLayout()
  const [draft, setDraft] = useState(sources.map(source => ({ ...source })))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const change = (index: number, patch: Partial<MarketSource>) => setDraft(rows => rows.map((source, i) => i === index ? { ...source, ...patch } : source))
  const save = async () => {
    setBusy(true); setError('')
    try {
      const { data } = await api('PUT', '/agent/capability-markets', { sources: draft })
      onSaved(data.sources)
    } catch (caught: any) { setError(capabilityError(caught.message, t)) } finally { setBusy(false) }
  }
  const form = <Form layout="vertical" disabled={busy} className="tt-capability-editor" onFinish={() => { void save() }}>
    <div className="tt-capability-editor-fields">
      {draft.map((source, index) => <fieldset className="tt-market-source-fields" key={index}>
        <legend>{source.name || t('capabilities.market.newSource')}</legend>
        <Form.Item label={t('capabilities.market.sourceName')} required><Input aria-label={t('capabilities.market.sourceName') + ' ' + (index + 1)} value={source.name} onChange={event => change(index, { name: event.target.value })} /></Form.Item>
        <Form.Item label={t('capabilities.market.sourceId')} required><Input aria-label={t('capabilities.market.sourceId') + ' ' + (index + 1)} value={source.id} onChange={event => change(index, { id: event.target.value })} /></Form.Item>
        <Form.Item label={t('capabilities.market.provider')}><Select aria-label={t('capabilities.market.provider') + ' ' + (index + 1)} value={source.provider} onChange={provider => change(index, { provider })} options={['skills_sh', 'mcp_registry', 'npm'].map(value => ({ value, label: t('capabilities.market.provider.' + value) }))} /></Form.Item>
        <Form.Item label={t('capabilities.market.sourceUrl')} required><Input aria-label={t('capabilities.market.sourceUrl') + ' ' + (index + 1)} value={source.url} onChange={event => change(index, { url: event.target.value })} /></Form.Item>
        <div className="tt-market-source-actions"><Switch aria-label={t('capabilities.market.enabled', { name: source.name })} checked={source.enabled} onChange={enabled => change(index, { enabled })} /><Button danger disabled={draft.length === 1 || busy} onClick={() => setDraft(rows => rows.filter((_, i) => i !== index))}>{t('capabilities.remove')}</Button></div>
      </fieldset>)}
      <Button disabled={draft.length >= 16 || busy} onClick={() => setDraft(rows => [...rows, { id: '', name: '', provider: 'mcp_registry', url: '', enabled: true }])}>{t('capabilities.market.addSource')}</Button>
    </div>
    {error && <Alert type="error" message={error} />}
    <div className="tt-capability-editor-actions"><Button disabled={busy} onClick={onClose}>{t('common.cancel')}</Button><Button type="primary" htmlType="submit" loading={busy}>{t('capabilities.saveChanges')}</Button></div>
  </Form>
  return phone ? <MobileSubPage title={t('capabilities.market.sources')} search={false} onBack={() => { if (!busy) onClose() }}>{form}</MobileSubPage> : <Modal open title={t('capabilities.market.sources')} footer={null} maskClosable={false} closable={!busy} keyboard={!busy} onCancel={onClose} className="tt-capability-modal tt-capability-editor-modal">{form}</Modal>
}
