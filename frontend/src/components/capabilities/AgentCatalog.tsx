import { usePageEffect } from '../../page-activity'
import BackButton from '../BackButton'
import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Input, Modal, Popconfirm, Select, Spin, message } from 'antd'
import { AgentLogo, RoamiLogo, GearIcon, SearchIcon } from '../../icons'
import RoamiAgentModels from './RoamiAgentModels'
import RoamiAgentMemory from './RoamiAgentMemory'
import { type AgentKind, agentName } from '../../agent-kind'
import { agentCommand } from '../../agent-command'
import { checkAgent, discoverAgents, installAgent, upgradeAgent, verifyAgent, type RegisteredAgent } from '../../agent-registry'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { preferencesLoaded, usePreferences, type Preferences } from '../../preferences'
import { pollWhileVisible } from '../../visible-poll'
import MobileSubPage from '../MobileSubPage'
import { AgentBalance } from './AgentBalance'
import AgentModels from './AgentModels'
import { onboardingChanged } from '../onboarding/onboarding-state'
import './capabilities.css'
import './agents.css'

const intervals = [30, 60, 300]
const commandKeys: Partial<Record<string, keyof Preferences>> = { claude: 'claudeCommand', codex: 'codexCommand', opencode: 'opencodeCommand', pi: 'piCommand' }

type AgentCatalogProps = { embedded?: boolean; mainVerified?: boolean; initialKind?: string; initialSection?: string; onSelect: (kind: string) => void; onLaunch?: (kind: AgentKind) => Promise<void> }
export function AgentCatalog(props: AgentCatalogProps) {
  if (props.initialKind === 'roami') return props.initialSection === 'memory'
    ? <RoamiAgentMemory onBack={() => props.onSelect('roami')} />
    : <RoamiAgentModels onBack={() => props.onSelect('')} onMemory={() => props.onSelect('roami/memory')} />
  return <ProfessionalAgentCatalog {...props} />
}
function ProfessionalAgentCatalog({ initialKind, initialSection, onSelect, onLaunch, embedded = false, mainVerified }: AgentCatalogProps) {
  const { t } = useI18n(), { phone } = useLayout()
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const [prefs, savePrefs] = usePreferences()
  const interval = intervals.includes(prefs.agentBalanceRefreshSeconds || 0) ? prefs.agentBalanceRefreshSeconds! : 60
  const [agents, setAgents] = useState<RegisteredAgent[] | null>(null)
  const [failed, setFailed] = useState(false), [version, setVersion] = useState(0)
  const [query, setQuery] = useState(''), [busy, setBusy] = useState('')
  const [launching, setLaunching] = useState(false)
  usePageEffect(() => {
    const changed = () => setVersion(value => value + 1)
    window.addEventListener('roam:agent-models-changed', changed)
    return () => window.removeEventListener('roam:agent-models-changed', changed)
  }, [])
  usePageEffect(() => {
    const poll = pollWhileVisible(async signal => {
      try {
        const rows = await discoverAgents(signal)
        if (!signal.aborted) { setAgents(rows); setFailed(false) }
      } catch (error) { if (!signal.aborted) setFailed(true); throw error }
    }, interval * 1000)
    return poll.stop
  }, [interval, version])
  const rows = agents || []
  const kinds = rows.map(row => row.kind)
  const names = Object.fromEntries(rows.map(row => [row.kind, row.displayName || (row.kind === 'claude' ? 'Claude Code' : agentName(row.kind))]))
  const description = (kind: string) => {
    const key = 'capabilities.agents.description.' + kind, text = t(key)
    return text === key ? t('capabilities.agents.description.registered') : text
  }
  const current = rows.find(row => row.kind === initialKind)?.kind || null
  const modelsOpen = initialSection === 'models' && rows.some(row => row.kind === current && row.models !== false)
  const selected = rows.find(row => row.kind === current)
  const close = () => onSelect('')
  const check = async (kind: AgentKind) => {
    if (busy) return
    setBusy('check:' + kind)
    try {
      const result = await checkAgent(kind)
      if (!mounted.current) return
      setAgents(value => value ? [...value.filter(row => row.kind !== kind), result] : [result]); onboardingChanged()
    } catch { message.error(t('capabilities.agents.checkFailed')) }
    finally { setBusy('') }
  }
  const install = async (kind: AgentKind) => {
    if (busy) return
    setBusy('install:' + kind)
    try {
      await installAgent(kind)
      if (!mounted.current) return
      message.success(t('agentDiscovery.installed')); setVersion(value => value + 1); onboardingChanged()
    } catch { message.error(t('agent.professional.installFailed')) }
    finally { setBusy('') }
  }
  const upgrade = async (kind: AgentKind) => {
    if (busy) return
    setBusy('upgrade:' + kind)
    try {
      const result = await upgradeAgent(kind)
      if (!mounted.current) return
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
  const installAction = (kind: AgentKind, row?: RegisteredAgent) => row && row.canInstall !== false && <Popconfirm classNames={{ root: 'tt-agent-install-confirm' }}
    title={t(row.installed ? 'capabilities.agents.updateConfirm' : 'agentDiscovery.installConfirm', { name: names[kind] })}
    onConfirm={() => row.installed ? upgrade(kind) : install(kind)} okText={t(row.installed ? 'capabilities.agents.update' : 'agentDiscovery.install')} cancelText={t('common.cancel')}>
    <Button disabled={!!busy || (row.installed && row.canUpgrade === false)} loading={busy === (row.installed ? 'upgrade:' : 'install:') + kind}>{t(row.installed ? 'capabilities.agents.update' : 'agentDiscovery.install')}</Button>
  </Popconfirm>
  const verify = async (kind: AgentKind) => {
    if (busy) return
    setBusy('verify:' + kind)
    try { const result = await verifyAgent(kind); if (!mounted.current) return; if (!result.verified) throw new Error('AGENT_VERIFICATION_FAILED'); setAgents(rows => [...(rows || []).filter(row => row.kind !== kind), result]); message.success(t('onboarding.verified')) }
    catch { message.error(t('onboarding.verifyFailed')) }
    finally { setBusy(''); onboardingChanged() }
  }
  const detail = current && <div className="tt-agent-detail">
    {embedded && !phone && <h3>{names[current]}</h3>}
    <dl><dt>{t('capabilities.agents.installation')}</dt><dd>{installation(selected)}</dd>
      <dt>{t(selected?.modelPreset ? 'capabilities.models.connection' : 'capabilities.agents.authentication')}</dt><dd>{authentication(selected)}</dd>
      <dt>{t('capabilities.agents.version')}</dt><dd>{selected?.version || t(selected?.versionState === 'unavailable' ? 'capabilities.agents.versionUnavailable' : 'capabilities.agents.versionUnchecked')}</dd>
      {selected?.binary && <><dt>{t('capabilities.agents.binary')}</dt><dd><code>{selected.binary}</code></dd></>}</dl>
    <div className="tt-agent-detail-actions">
      {onLaunch && selected?.interactive !== false && <Button type="primary" disabled={!selected?.installed || !!busy || !preferencesLoaded()} loading={launching} onClick={() => { void launch() }}>{t('capabilities.agents.openTerminal')}</Button>}
      <Button loading={busy === 'check:' + current} disabled={!!busy} onClick={() => { void check(current) }}>{t('capabilities.agents.check')}</Button>
      {installAction(current, selected)}
      <Button loading={busy === 'verify:' + current} disabled={!selected?.installed || !!busy} onClick={() => { void verify(current) }}>{t('onboarding.verify')}</Button>
      {selected?.verified && <span role="status">{t('onboarding.verified')}</span>}
      {selected?.models !== false && <Button disabled={!!busy} onClick={() => onSelect(current + '/models')}>{t('capabilities.models.manage')}</Button>}
    </div>
    {selected?.installed && selected.canUpgrade === false && <p>{t('capabilities.agents.manualUpgrade')}</p>}
    <p>{t(selected?.interactive === false ? 'capabilities.agents.headlessHint' : 'capabilities.agents.loginHint', { command: selected?.setupCommand || selected?.command || current })}</p><p>{t('onboarding.verifyHint')}</p>
    {selected && <AgentCommandForm key={current} kind={current} defaultCommand={selected.command} />}
    {selected?.installed && <AgentBalance agent={selected} detail />}
  </div>
  const models = current && selected?.models !== false && <AgentModels key={current} kind={current} installed={selected?.installed === true} setup={<div className="tt-agent-model-toolbar"><span>{installation(selected)}{selected?.version && ' · ' + selected.version}</span><div className="tt-agent-detail-actions">{installAction(current, selected)}{onLaunch && selected?.interactive !== false && <Button disabled={!selected?.installed || !!busy || !preferencesLoaded()} loading={launching} onClick={() => { void launch() }}>{t('capabilities.agents.openTerminal')}</Button>}</div></div>} />
  const filtered = kinds.filter(kind => `${names[kind]} ${description(kind)}`.toLowerCase().includes(query.trim().toLowerCase()))
  if (embedded && current) return <section className="onboarding-agent-detail">{!phone && <BackButton onClick={close} />}{modelsOpen ? models : detail}</section>
  return <section className="tt-capability-catalog" data-kind="agents">
    <div className="tt-capability-toolbar"><Input prefix={<SearchIcon size={16} />} aria-label={t('capabilities.agents.search')} placeholder={t('capabilities.agents.search')} value={query} onChange={event => setQuery(event.target.value)} allowClear /></div>
    {failed && <Alert type="error" className="tt-capability-alert" showIcon message={t('agent.professional.loadFailed')} action={<Button onClick={() => setVersion(value => value + 1)}>{t('agent.retry')}</Button>} />}
    {!agents && !failed && <Spin />}
    {agents && !filtered.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('capabilities.agents.empty')} />}
    <div className="tt-capability-list">{!query && <article className="tt-capability-row" aria-label={t('hub.roamiModels')}><div className="tt-capability-cardhead"><span className="tt-agentmark"><RoamiLogo size={32} /></span><strong>Roami</strong></div><p className="tt-capability-description">{t('hub.roamiModels')}</p>{mainVerified !== undefined && <span role="status">{t(mainVerified ? 'onboarding.verified' : 'onboarding.pending')}</span>}<button type="button" className="tt-act" onClick={() => onSelect('roami')}>{t('capabilities.agents.manage')}</button></article>}{filtered.map(kind => {
      const row = rows.find(row => row.kind === kind)
      return <article className="tt-capability-row" key={kind} aria-label={names[kind]}>
        <div className="tt-capability-cardhead tt-agent-cardhead"><span className="tt-agentmark"><AgentLogo kind={kind} size={32} /></span>
          <span className={'tt-capability-connection' + (row?.installed ? ' connected' : '')}><i aria-hidden="true" />{installation(row)}</span></div>
        <div className="tt-agent-identity">
          <button type="button" className="tt-capability-open" onClick={() => onSelect(kind)}><strong>{names[kind]}</strong></button>
          {row?.installed && <span className="tt-agent-version">{row.version || t('capabilities.agents.versionUnknown')}</span>}
        </div>
        <p className="tt-capability-description">{description(kind)}</p>
        <div className="tt-agent-meta"><span>{row?.verified ? t('onboarding.verified') : authentication(row)}</span></div>
        {row?.installed && <AgentBalance agent={row} />}
        <div className="tt-capability-cardfooter"><div><button type="button" className="tt-act" onClick={() => onSelect(kind)}><GearIcon size={14} />{t('capabilities.agents.manage')}</button>
          {row?.models !== false && <button type="button" className="tt-act" onClick={() => onSelect(kind + '/models')}>{t('capabilities.models.manage')}</button>}</div>
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

function AgentCommandForm({ kind, defaultCommand }: { kind: AgentKind; defaultCommand?: string }) {
  const { t } = useI18n()
  const [prefs, savePrefs] = usePreferences()
  const [draft, setDraft] = useState(''), [baseline, setBaseline] = useState('')
  const [ready, setReady] = useState(false), [saving, setSaving] = useState(false), [failed, setFailed] = useState(false)
  const hydrated = useRef(false)
  const key = commandKeys[kind]
  useEffect(() => {
    if (hydrated.current || !preferencesLoaded()) return
    const command = agentCommand(kind, prefs, defaultCommand)
    hydrated.current = true; setDraft(command); setBaseline(command); setReady(true)
  }, [prefs, key, kind, defaultCommand])
  const save = async () => {
    if (!ready || saving) return
    setSaving(true); setFailed(false)
    const value = draft.trim() || defaultCommand || kind
    try {
      const ok = await savePrefs({ agentCommands: { ...prefs.agentCommands, [kind]: value }, ...(key ? { [key]: value } : {}) } as Partial<Preferences>)
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
