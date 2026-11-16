import { useEffect, useState } from 'react'
import { App } from 'antd'
import { Button, TabBar } from './model-controls'
import { CopyIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { ModelCatalog } from './model-hub-api'
import GatewayAccessKeys from './GatewayAccessKeys'
import GatewayModelDirectory from './GatewayModelDirectory'

export default function ModelGatewayWorkspace({ active, catalog, onChanged, onSource }: { active: boolean; catalog: ModelCatalog; onChanged: () => void; onSource: (id: string) => void }) {
  const { t } = useI18n(), { message } = App.useApp()
  const [tab, setTab] = useState('access'), [keyDraft, setKeyDraft] = useState('')
  const [visited,setVisited]=useState(active), [directoryVisited,setDirectoryVisited]=useState(false)
  useEffect(()=>{if(active)setVisited(true)},[active])
  const endpoint = catalog.baseUrl ? catalog.baseUrl + '/v1' : ''
  return <section className="tt-model-gateway" hidden={!active} aria-label={t('hub.tab.gateway')}>
    <header className="tt-pagehead"><h2>{t('hub.tab.gateway')}</h2></header>
    <TabBar activeKey={tab} onChange={value=>{setTab(value);if(value==='directory')setDirectoryVisited(true)}} items={['access', 'directory'].map(key => ({ key, label: t('modelInteraction.gateway.' + key) }))} />
    {visited && <div hidden={tab !== 'access'}>
      <section className="tt-gateway-endpoint" aria-label={t('agent.models.baseUrl')}>
        <div><h3>{t('agent.models.baseUrl')}</h3><code>{endpoint}</code><p className="agent-settings-hint">{t('hub.entryHint')}</p></div>
        <Button icon={<CopyIcon />} disabled={!endpoint} onClick={async () => { try { await navigator.clipboard.writeText(endpoint); message.success(t('common.copied')) } catch { message.error(t('hub.gateway.copyFailed')) } }}>{t('common.copy')}</Button>
      </section>
      <GatewayAccessKeys active={active && tab==='access'} onChanged={onChanged} value={keyDraft} onChange={setKeyDraft} />
    </div>}
    {directoryVisited && <div hidden={tab !== 'directory'}><GatewayModelDirectory catalog={catalog} onSource={onSource} /></div>}
  </section>
}
