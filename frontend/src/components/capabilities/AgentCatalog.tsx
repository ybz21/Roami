import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Input, Modal, Popconfirm, Select, Spin, message } from 'antd'
import { AgentLogo, BotIcon, GearIcon, SearchIcon } from '../../icons'
import RoamiAgentModels from './RoamiAgentModels'
import { type AgentKind, isAgentKind } from '../../agent-kind'
import { checkAgent, discoverAgents, installAgent, upgradeAgent, type RegisteredAgent } from '../../agent-registry'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { preferencesLoaded, usePreferences, type Preferences } from '../../preferences'
import { pollWhileVisible } from '../../visible-poll'
import MobileSubPage from '../MobileSubPage'
import { AgentBalance } from './AgentBalance'
import AgentModels from './AgentModels'
import './agents.css'

const kinds: AgentKind[] = ['claude', 'codex', 'opencode', 'pi']
const names: Record<AgentKind, string> = { claude: 'Claude Code', codex: 'Codex', opencode: 'OpenCode', pi: 'Pi' }
const intervals = [30, 60, 300]
const commandKey = (kind: AgentKind) => `${kind}Command` as 'claudeCommand' | 'codexCommand' | 'opencodeCommand' | 'piCommand'

export function AgentCatalog({ initialKind, initialSection, onSelect, onLaunch }: { initialKind?: string; initialSection?: string; onSelect: (kind: string) => void; onLaunch?: (kind: AgentKind) => Promise<void> }) {
  return initialKind === 'roami' ? <RoamiAgentModels onBack={() => onSelect('')} /> : <ProfessionalAgentCatalog initialKind={initialKind} initialSection={initialSection} onSelect={onSelect} onLaunch={onLaunch} />
}
function ProfessionalAgentCatalog({ initialKind, initialSection, onSelect, onLaunch }: { initialKind?: string; initialSection?: string; onSelect: (kind: string) => void; onLaunch?: (kind: AgentKind) => Promise<void> }) {
  const { t } = useI18n(), { phone } = useLayout()
  const [prefs, savePrefs] = usePreferences()
  const interval = intervals.includes(prefs.agentBalanceRefreshSeconds || 0) ? prefs.agentBalanceRefreshSeconds! : 60
  const [agents, setAgents] = useState<RegisteredAgent[] | null>(null)
  const [failed, setFailed] = useState(false), [version, setVersion] = useState(0)
  const [query, setQuery] = useState(''), [busy, setBusy] = useState('')
  const [launching, setLaunching] = useState(false)
  useEffect(() => {
    const changed = () => setVersion(value => value + 1)
    window.addEventListener('roam:agent-models-changed', changed)
    return () => window.removeEventListener('roam:agent-models-changed', changed)
  }, [])
  useEffect(() => {
    const poll = pollWhileVisible(async signal => {
      try {
        const rows = await discoverAgents(signal)
        if (!signal.aborted) { setAgents(rows); setFailed(false) }
      } catch (error) { if (!signal.aborted) setFailed(true); throw error }
    }, interval * 1000)
    return poll.stop
  }, [interval, version])
  const rows = agents || []
  const current = isAgentKind(initialKind) ? initialKind : null
  const modelsOpen = initialSection === 'models'
  const selected = rows.find(row => row.kind === current)
  const close = () => onSelect('')
  const check = async (kind: AgentKind) => {
    if (busy) return
    setBusy('check:' + kind)
    try {
      const result = await checkAgent(kind)
      setAgents(value => value ? [...value.filter(row => row.kind !== kind), result] : [result])
    } catch { message.error(t('capabilities.agents.checkFailed')) }
    finally { setBusy('') }
  }
  const install = async (kind: AgentKind) => {
    if (busy) return
    setBusy('install:' + kind)
    try {
      await installAgent(kind)
      message.success(t('agentDiscovery.installed')); setVersion(value => value + 1)
    } catch { message.error(t('agent.professional.installFailed')) }
    finally { setBusy('') }
  }
  const upgrade = async (kind: AgentKind) => {
    if (busy) return
    setBusy('upgrade:' + kind)
    try {
      const result = await upgradeAgent(kind)
      setAgents(previous => previous ? previous.map(row => row.kind === kind ? result : row) : [result])
      message.success(t('capabilities.agents.upgraded'))
    } catch (cause) {
      const code = (cause as { apiError?: { code?: string } })?.apiError?.code
      if (code === 'AGENT_UPGRADE_UNVERIFIED') setVersion(value => value + 1)
      message.error(t(code === 'AGENT_UPGRADE_UNSUPPORTED' ? 'capabilities.agents.manualUpgrade' : code === 'AGENT_MAINTENANCE_BUSY' ? 'capabilities.agents.maintenanceBusy' : code === 'AGENT_UPGRADE_UNVERIFIED' ? 'capabilities.agents.upgradeUnverified' : 'capabilities.agents.upgradeFailed'))
    } finally { setBusy('') }
  }
  const installation = (row?: RegisteredAgent) => t(!row ? 'agent.professional.probeUnknown' : row.installed ? 'agent.professional.installed' : 'agent.professional.missing')
  const authentication = (row?: RegisteredAgent) => row?.modelPreset ? t('capabilities.models.presetName', { name: row.modelPreset }) : t('capabilities.agents.auth.' + (row?.authentication || 'unknown'))
  const launch = async () => {
    if (!current || !onLaunch || launching || !preferencesLoaded()) return
    setLaunching(true)
    try { await onLaunch(current) } catch { message.error(t('capabilities.agents.openFailed')) }
    finally { setLaunching(false) }
  }
  const installAction = (kind: AgentKind, row?: RegisteredAgent) => row && <Popconfirm classNames={{ root: 'tt-agent-install-confirm' }}
    title={t(row.installed ? 'capabilities.agents.updateConfirm' : 'agentDiscovery.installConfirm', { name: names[kind] })}
    onConfirm={() => row.installed ? upgrade(kind) : install(kind)} okText={t(row.installed ? 'capabilities.agents.update' : 'agentDiscovery.install')} cancelText={t('common.cancel')}>
    <Button disabled={!!busy || (row.installed && row.canUpgrade === false)} loading={busy === (row.installed ? 'upgrade:' : 'install:') + kind}>{t(row.installed ? 'capabilities.agents.update' : 'agentDiscovery.install')}</Button>
  </Popconfirm>
  const detail = current && <div className="tt-agent-detail">
    <dl><dt>{t('capabilities.agents.installation')}</dt><dd>{installation(selected)}</dd>
      <dt>{t(selected?.modelPreset ? 'capabilities.models.connection' : 'capabilities.agents.authentication')}</dt><dd>{authentication(selected)}</dd>
      <dt>{t('capabilities.agents.version')}</dt><dd>{selected?.version || t(selected?.versionState === 'unavailable' ? 'capabilities.agents.versionUnavailable' : 'capabilities.agents.versionUnchecked')}</dd>
      {selected?.binary && <><dt>{t('capabilities.agents.binary')}</dt><dd><code>{selected.binary}</code></dd></>}</dl>
    <div className="tt-agent-detail-actions">
      {onLaunch && <Button type="primary" disabled={!selected?.installed || !!busy || !preferencesLoaded()} loading={launching} onClick={() => { void launch() }}>{t('capabilities.agents.openTerminal')}</Button>}
      <Button loading={busy === 'check:' + current} disabled={!!busy} onClick={() => { void check(current) }}>{t('capabilities.agents.check')}</Button>
      {installAction(current, selected)}
      <Button disabled={!!busy} onClick={() => onSelect(current + '/models')}>{t('capabilities.models.manage')}</Button>
    </div>
    {selected?.installed && selected.canUpgrade === false && <p>{t('capabilities.agents.manualUpgrade')}</p>}
    <p>{t('capabilities.agents.loginHint')}</p>
    <AgentCommandForm key={current} kind={current} />
    {selected?.installed && <AgentBalance agent={selected} detail />}
  </div>
  const models = current && <AgentModels key={current} kind={current} installed={selected?.installed === true} setup={<div className="tt-agent-model-toolbar"><span>{installation(selected)}{selected?.version && ' · ' + selected.version}</span><div className="tt-agent-detail-actions">{installAction(current, selected)}{onLaunch && <Button disabled={!selected?.installed || !!busy || !preferencesLoaded()} loading={launching} onClick={() => { void launch() }}>{t('capabilities.agents.openTerminal')}</Button>}</div></div>} />
  const filtered = kinds.filter(kind => `${names[kind]} ${t('capabilities.agents.description.' + kind)}`.toLowerCase().includes(query.trim().toLowerCase()))
  return <section className="tt-capability-catalog" data-kind="agents">
    <div className="tt-capability-toolbar"><Input prefix={<SearchIcon size={16} />} aria-label={t('capabilities.agents.search')} placeholder={t('capabilities.agents.search')} value={query} onChange={event => setQuery(event.target.value)} allowClear /></div>
    {failed && <Alert type="error" className="tt-capability-alert" showIcon message={t('agent.professional.loadFailed')} action={<Button onClick={() => setVersion(value => value + 1)}>{t('agent.retry')}</Button>} />}
    {!agents && !failed && <Spin />}
    {!filtered.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('capabilities.agents.empty')} />}
    <div className="tt-capability-list">{!query && <article className="tt-capability-row"><div className="tt-capability-cardhead"><BotIcon size={32} /><strong>Roami</strong></div><p className="tt-capability-description">{t('hub.roamiModels')}</p><button type="button" className="tt-act" onClick={() => onSelect('roami')}>{t('capabilities.agents.manage')}</button></article>}{filtered.map(kind => {
      const row = rows.find(row => row.kind === kind)
      return <article className="tt-capability-row" key={kind} aria-label={names[kind]}>
        <div className="tt-capability-cardhead tt-agent-cardhead"><span className="tt-agentmark"><AgentLogo kind={kind} size={32} /></span>
          <span className={'tt-capability-connection' + (row?.installed ? ' connected' : '')}><i aria-hidden="true" />{installation(row)}</span></div>
        <div className="tt-agent-identity">
          <button type="button" className="tt-capability-open" onClick={() => onSelect(kind)}><strong>{names[kind]}</strong></button>
          {row?.installed && <span className="tt-agent-version">{row.version || t('capabilities.agents.versionUnknown')}</span>}
        </div>
        <p className="tt-capability-description">{t('capabilities.agents.description.' + kind)}</p>
        <div className="tt-agent-meta"><span>{authentication(row)}</span></div>
        {row?.installed && <AgentBalance agent={row} />}
        <div className="tt-capability-cardfooter"><div><button type="button" className="tt-act" onClick={() => onSelect(kind)}><GearIcon size={14} />{t('capabilities.agents.manage')}</button>
          <button type="button" className="tt-act" onClick={() => onSelect(kind + '/models')}>{t('capabilities.models.manage')}</button></div>
          <div>{installAction(kind, row)}</div>
        </div>
        {row?.installed && row.canUpgrade === false && <p className="tt-agent-upgrade-hint">{t('capabilities.agents.manualUpgrade')}</p>}
      </article>
    })}</div>
    <div className="tt-agent-cadence"><span>{t('agent.professional.refreshInterval')}</span><Select aria-label={t('agent.professional.refreshInterval')} value={interval}
      options={intervals.map(seconds => ({ value: seconds, label: t('agent.professional.everySeconds', { seconds }) }))}
      onChange={seconds => { void savePrefs({ agentBalanceRefreshSeconds: seconds }).then(ok => { if (!ok) message.error(t('settings.preference.failed')) }) }} /></div>
    {phone ? current && <MobileSubPage title={modelsOpen ? t('capabilities.models.title', { name: names[current] }) : names[current]} search={false} onBack={close} manageHistory={false} keepBottomNav>
      {modelsOpen ? models : <div className="tt-capability-detail-scroll">{detail}</div>}</MobileSubPage>
      : <Modal open={!!current} title={current ? modelsOpen ? t('capabilities.models.title', { name: names[current] }) : names[current] : ''} onCancel={close} footer={null} width="var(--content-form)" className={'tt-capability-modal' + (modelsOpen ? ' tt-agent-model-modal' : '')} destroyOnClose>
        {modelsOpen && current ? models : detail}</Modal>}
  </section>
}

function AgentCommandForm({ kind }: { kind: AgentKind }) {
  const { t } = useI18n()
  const [prefs, savePrefs] = usePreferences()
  const [draft, setDraft] = useState(''), [baseline, setBaseline] = useState('')
  const [ready, setReady] = useState(false), [saving, setSaving] = useState(false), [failed, setFailed] = useState(false)
  const hydrated = useRef(false)
  const key = commandKey(kind)
  useEffect(() => {
    if (hydrated.current || !preferencesLoaded()) return
    const command = prefs[key] || kind
    hydrated.current = true; setDraft(command); setBaseline(command); setReady(true)
  }, [prefs, key, kind])
  const save = async () => {
    if (!ready || saving) return
    setSaving(true); setFailed(false)
    const value = draft.trim() || kind
    try {
      const ok = await savePrefs({ [key]: value } as Partial<Preferences>)
      if (!ok) { setFailed(true); return }
      setBaseline(value); setDraft(value); message.success(t('capabilities.agents.saved'))
    } catch { setFailed(true) } finally { setSaving(false) }
  }
  return <form className="tt-agent-command" onSubmit={event => { event.preventDefault(); void save() }}>
    <label>{t('capabilities.agents.command')}<Input aria-label={t('capabilities.agents.command')} value={draft} placeholder={kind} disabled={!ready || saving} autoComplete="off" onChange={event => setDraft(event.target.value)} /></label>
    <p>{t('capabilities.agents.commandHint')}</p>
    {failed && <Alert type="error" showIcon message={t('settings.preference.failed')} />}
    <Button type="primary" htmlType="submit" disabled={!ready || draft === baseline} loading={saving}>{t('capabilities.saveChanges')}</Button>
  </form>
}
