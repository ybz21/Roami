import { useEffect, useState } from 'react'
import { Button, Modal, Popconfirm, Dropdown, Spin, message } from 'antd'
import { AgentLogo, ChevronRight, ClockIcon } from '../../icons'
import { isAgentKind } from '../../agent-kind'
import { discoverAgents, installAgent, type RegisteredAgent } from '../../agent-registry'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { usePreferences } from '../../preferences'
import { useCurrentNodeId } from '../cluster/node-url'
import MobileSubPage from '../MobileSubPage'
import { TextControl } from './SettingRow'
import type { SettingItem } from './registry'
import './agent-settings.css'

const names: Record<string, string> = { claude: 'Claude Code', codex: 'Codex', opencode: 'OpenCode', pi: 'Pi' }
const refreshOptions = [30, 60, 300]

export function ProfessionalAgents({ items }: { items: SettingItem[] }) {
  const node = useCurrentNodeId()
  return <ProfessionalAgentList key={node || 'local'} items={items} />
}

function ProfessionalAgentList({ items }: { items: SettingItem[] }) {
  const { t } = useI18n(), { phone } = useLayout()
  const [prefs, savePrefs] = usePreferences()
  const interval = refreshOptions.includes(prefs.agentBalanceRefreshSeconds || 0) ? prefs.agentBalanceRefreshSeconds! : 60
  const [agents, setAgents] = useState<RegisteredAgent[] | null>(null)
  const [error, setError] = useState(false), [version, setVersion] = useState(0)
  const [busy, setBusy] = useState(''), [selected, setSelected] = useState<string | null>(null)
  useEffect(() => {
    const abort = new AbortController()
    let pending = false
    const reload = async () => {
      if (pending || document.hidden) return
      pending = true
      try {
        const rows = await discoverAgents(abort.signal)
        if (!abort.signal.aborted) { setAgents(rows); setError(false) }
      } catch {
        if (!abort.signal.aborted) setError(true)
      } finally { pending = false }
    }
    void reload()
    const timer = window.setInterval(() => { void reload() }, interval * 1000)
    document.addEventListener('visibilitychange', reload)
    return () => { abort.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', reload) }
  }, [interval, version])

  const install = async (kind: string) => {
    if (busy) return
    setBusy(kind)
    try { await installAgent(kind); message.success(t('agentDiscovery.installed')); setVersion(v => v + 1) }
    catch { message.error(t('agent.professional.installFailed')) }
    finally { setBusy('') }
  }
  const current = items.find(item => item.id === selected)
  const selectedKind = current?.id.replace(/Command$/, '') || ''
  const selectedAgent = agents?.find(row => row.kind === selectedKind)
  const detail = current && <>
    <AgentBalance agent={selectedAgent} detail />
    <p className="agent-settings-hint">{t(selectedKind === 'claude' ? 'agent.professional.claudeHelp' : selectedKind === 'codex' ? 'agent.professional.codexHelp' : 'agent.professional.providerHelp')}</p>
    <details className="agent-model-advanced"><summary>{t('agent.professional.advanced')}</summary>{current.control.kind === 'text' && <label>{current.label}<TextControl key={current.id} label={current.label} get={current.control.get} set={current.control.set} placeholder={current.control.placeholder} /></label>}<p className="agent-settings-hint">{current.desc}</p></details>
  </>

  return <section className="professional-agents">
    {error && <div className="agent-settings-error" role="alert">{t('agent.professional.loadFailed')} <Button onClick={() => setVersion(v => v + 1)}>{t('agent.retry')}</Button></div>}
    {!agents && !error && <Spin />}
    <div className="professional-agent-list">{items.map(item => {
      const kind = item.id.replace(/Command$/, '')
      const agent = agents?.find(row => row.kind === kind)
      return <article className="professional-agent" key={item.id}>
        <button type="button" className="professional-agent-open" aria-label={t('agent.professional.manage', { name: names[kind] })} aria-describedby={agent?.installed ? `agent-balance-${kind}` : undefined} onClick={() => setSelected(item.id)}>
          <span className="professional-agent-identity"><span className="tt-agentmark">{isAgentKind(kind) && <AgentLogo kind={kind} size={24} />}</span><strong>{names[kind]}</strong><span className="professional-agent-status">{agent && t(agent.installed ? 'agent.professional.installed' : 'agent.professional.missing')}</span><ChevronRight size={16} /></span>
          {agent?.installed && <AgentBalance agent={agent} id={`agent-balance-${kind}`} />}
        </button>
        {agent && !agent.installed && <Popconfirm title={t('agentDiscovery.installConfirm', { name: names[kind] })} onConfirm={() => install(kind)} okText={t('agentDiscovery.install')} cancelText={t('common.cancel')}><Button className="professional-agent-install" disabled={!!busy} loading={busy === kind}>{t('agentDiscovery.install')}</Button></Popconfirm>}
      </article>
    })}</div>
    <Dropdown trigger={['click']} overlayClassName="professional-agent-refresh-menu" menu={{ selectable: true, selectedKeys: [String(interval)], onClick: ({ key }) => savePrefs({ agentBalanceRefreshSeconds: Number(key) }), items: refreshOptions.map(seconds => ({ key: String(seconds), label: t('agent.professional.everySeconds', { seconds }) })) }}>
      <button type="button" className="professional-agent-cadence" aria-label={t('agent.professional.refreshInterval')}><ClockIcon size={14} />{t('agent.professional.autoRefresh', { seconds: interval })}</button>
    </Dropdown>
    {phone ? current && <MobileSubPage title={names[selectedKind]} onBack={() => setSelected(null)} dialogLabel={names[selectedKind]} keepBottomNav><div className="agent-professional-detail">{detail}</div></MobileSubPage> : <Modal className="agent-capability-dialog" open={!!current} centered title={current ? names[selectedKind] : ''} footer={null} onCancel={() => setSelected(null)}><div className="agent-professional-detail-content">{detail}</div></Modal>}
  </section>
}

export function AgentBalance({ agent, detail = false, id }: { agent?: RegisteredAgent; detail?: boolean; id?: string }) {
  const { t, locale } = useI18n()
  const q = agent?.quota
  const windows = q?.state === 'available' ? (q.windows?.length ? q.windows : q.remainingPercent !== undefined ? [{ remainingPercent: q.remainingPercent, windowMinutes: q.windowMinutes || 0, resetsAt: q.resetsAt }] : []).filter(window => !window.resetsAt || window.resetsAt * 1000 > Date.now()) : []
  const reason = q?.reason || 'no_snapshot'
  return <span className="agent-balance" id={id}>
    {windows.length ? windows.map((window, index) => <span className="agent-balance-window" key={index}>
      <span className="agent-balance-values"><span>{t(window.windowMinutes % 1440 === 0 ? 'agent.professional.periodDays' : 'agent.professional.periodHours', { n: window.windowMinutes % 1440 === 0 ? window.windowMinutes / 1440 : Number((window.windowMinutes / 60).toFixed(1)) })}</span><strong>{t('agent.professional.remaining', { percent: Math.round(window.remainingPercent) })}</strong></span>
      <progress className="agent-balance-meter" aria-label={t('agent.professional.remaining', { percent: Math.round(window.remainingPercent) })} max={100} value={Math.max(0, Math.min(100, window.remainingPercent))} />
      {window.resetsAt && <span className="agent-balance-reset">{t('agent.professional.resetsAt', { time: new Date(window.resetsAt * 1000).toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) })}</span>}
    </span>) : <span className="agent-balance-unavailable">{t(`agent.professional.reason.${reason}`)}</span>}
    {detail && !!windows.length && q?.observedAt && <span className="agent-settings-hint">{t('agentDiscovery.observed', { time: new Date(q.observedAt).toLocaleString(locale) })}</span>}
  </span>
}
