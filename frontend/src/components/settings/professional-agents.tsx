import { useState } from 'react'
import { Input, Modal, Tag } from 'antd'
import { AgentLogo, TerminalIcon } from '../../icons'
import { useI18n } from '../../i18n'
import type { SettingItem } from './registry'
import './agent-settings.css'

const names: Record<string, string> = { claudeCommand: 'Claude Code', codexCommand: 'Codex', opencodeCommand: 'OpenCode', piCommand: 'Pi' }
export function ProfessionalAgents({ items }: { items: SettingItem[] }) {
  const { t } = useI18n()
  const [selected, setSelected] = useState<string | null>(null)
  const current = items.find(item => item.id === selected)
  return <section className="agent-capabilities"><p className="agent-settings-hint">{t('agent.professional.hint')}</p><div className="agent-capability-grid">{items.map(item => <article className="agent-capability-card" key={item.id}>
    <div className="agent-capability-cardtop"><span className="tt-agentmark">{item.id === 'claudeCommand' || item.id === 'codexCommand' ? <AgentLogo kind={item.id === 'claudeCommand' ? 'claude' : 'codex'} size={24} /> : <TerminalIcon size={24} />}</span><div className="agent-capability-heading"><strong>{names[item.id]}</strong><span className="agent-settings-hint">{t('agent.professional.sessionLaunch')}</span></div></div>
    <p className="agent-capability-description">{t(item.id === 'claudeCommand' || item.id === 'codexCommand' ? 'agent.professional.tracked' : 'agent.professional.launchOnly')}</p><p className="agent-settings-hint">{t('agent.professional.usageUnknown')}</p>
    <div className="agent-capability-footer"><Tag>{t('agent.professional.probeUnknown')}</Tag><button type="button" className="tt-act" onClick={() => setSelected(item.id)}>{t('agent.professional.details')}</button></div>
  </article>)}</div><Modal className="agent-capability-dialog" open={!!current} centered title={current ? names[current.id] : ''} footer={null} onCancel={() => setSelected(null)}><p className="agent-settings-hint">{t('agent.professional.usageHint')}</p><details className="agent-model-advanced"><summary>{t('agent.professional.advanced')}</summary>{current?.control.kind === 'text' && <label>{current.label}<Input aria-label={current.label} placeholder={current.control.placeholder} value={current.control.get()} onChange={event => { if (current.control.kind === 'text') current.control.set(event.target.value) }} /></label>}<p className="agent-settings-hint">{current?.desc}</p></details></Modal></section>
}
