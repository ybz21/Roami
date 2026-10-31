import { useState } from 'react'
import { Alert, App, Button, Select, Spin } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import MobileSubPage from '../MobileSubPage'
import { AgentSettingsForm } from '../settings/agent-settings'
import { catalogFailure, useModelCatalog } from './model-hub-api'
import './model-hub.css'

export default function RoamiAgentModels({ onBack }: { onBack: () => void }) {
  const { t } = useI18n(), { phone } = useLayout()
  const { modal, message } = App.useApp(), catalog = useModelCatalog()
  const [main, setMain] = useState(''), [worker, setWorker] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [advanced, setAdvanced] = useState(false)
  const options = (catalog.value?.models || []).filter(model => model.protocol === 'openai-completions').map(model => ({ value: model.id, label: model.name }))
  const chosen = (role: string, draft: string) => draft || (options.some(model => model.value === catalog.value?.roamiModels?.[role]) ? catalog.value?.roamiModels?.[role] : options[0]?.value)
  const apply = async (restore = false) => {
    if (!catalog.value || busy) return
    setBusy(true); setError('')
    try {
      await api('POST', '/agent/model-gateway/catalog/roles', { main: chosen('main', main) || '', worker: chosen('worker', worker) || '', revision: catalog.value.revision, restore })
      setAdvanced(false); catalog.retry(); message.success(t(restore ? 'capabilities.models.restored' : 'agent.models.saved'))
      window.dispatchEvent(new Event('roami:agent-model-settings-changed'))
    } catch (cause) { setError(catalogFailure(cause)) } finally { setBusy(false) }
  }
  const body = <div className="tt-model-hub-scroll"><div className="agent-settings-form">
    {(error || catalog.error) && <Alert type="error" message={t(error || catalog.error)} action={<Button onClick={catalog.retry}>{t('capabilities.models.reread')}</Button>} />}
    {!catalog.value && !catalog.error ? <Spin /> : <>
      <p className="agent-settings-hint">{t('hub.roamiBindingHint')}</p>
      {(['main', 'worker'] as const).map(role => <label className="agent-settings-field" key={role}>{t('agent.models.role.' + role)}<Select virtual={false} classNames={{ popup: { root: 'tt-capability-select-popup' } }} aria-label={t('agent.models.role.' + role)} value={chosen(role, role === 'main' ? main : worker)} options={options} onChange={role === 'main' ? setMain : setWorker} disabled={busy} /></label>)}
      {!options.length && <p>{t('hub.noCompatible')}</p>}
      <div className="tt-model-binding-actions"><Button type="primary" loading={busy} disabled={!chosen('main', main) || !chosen('worker', worker)} onClick={() => modal.confirm({ title: t('hub.useGateway'), content: t('hub.roamiApplyScope'), onOk: () => apply() })}>{t('capabilities.models.apply')}</Button>
      <Button disabled={!catalog.value?.canRestoreRoami || busy} onClick={() => modal.confirm({ title: t('capabilities.models.restore'), content: t('capabilities.models.restoreConfirm'), onOk: () => apply(true) })}>{t('capabilities.models.restore')}</Button></div>
    </>}
    <details open={advanced} onToggle={event => setAdvanced(event.currentTarget.open)}><summary>{t('agent.models.advanced')}</summary>{advanced && <AgentSettingsForm key={catalog.value?.revision} onModelNames={() => {}} />}</details>
  </div></div>
  return phone ? <MobileSubPage title={t('hub.roamiModels')} search={false} onBack={onBack} manageHistory={false} keepBottomNav>{body}</MobileSubPage> : <div className="tt-model-hub-roami"><div className="tt-model-hub-detail-head"><h3>{t('hub.roamiModels')}</h3><Button onClick={onBack}>{t('common.back')}</Button></div>{body}</div>
}
