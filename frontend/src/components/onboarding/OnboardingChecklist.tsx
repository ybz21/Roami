import { Button } from 'antd'
import { BotIcon, CheckIcon, ChevronRight, FolderIcon, LinkIcon, TerminalIcon } from '../../icons'
import { useI18n } from '../../i18n'
import { useOnboardingState, nextOnboardingStep, steps } from './onboarding-state'
import './onboarding.css'

export default function OnboardingChecklist({ onNav, force = false }: { onNav: (route: string) => void; force?: boolean }) {
  const { t } = useI18n(), state = useOnboardingState()
  if ((!force && !state.visible) || !state.value || state.failed) return null
  const done = [state.hasModels, !!state.value.models.verified && state.readyAgents.length > 0, state.value.projects.length > 0, state.progress.completed]
  const icons = [LinkIcon, BotIcon, FolderIcon, TerminalIcon]
  const begin = () => { void state.change({ started: true }); onNav('onboarding/' + nextOnboardingStep(state.value!, state.progress)) }
  return <section className="onboarding-welcome" aria-label={t('onboarding.title')}>
    <header className="tt-pagehead"><div className="ttl"><h2>{t('onboarding.welcome')}</h2></div>
      <div className="acts"><Button type="primary" onClick={begin}>{t(state.progress.started ? 'onboarding.continue' : 'onboarding.begin')}</Button><Button type="text" onClick={() => onNav('onboarding/tour')}>{t('onboarding.tour')}</Button><Button type="text" onClick={() => { void state.change({ dismissed: true }) }}>{t('onboarding.later')}</Button></div>
    </header>
    <div className="onboarding-checklist">{steps.map((step, index) => { const Icon = icons[index]; return <button type="button" key={step} onClick={() => { void state.change({ started: true }); onNav('onboarding/' + step) }}><span className={done[index] ? 'onboarding-done' : ''}>{done[index] ? <CheckIcon size={20} /> : <Icon size={20} />}</span><span><strong>{t('onboarding.step.' + step)}</strong><small>{t('onboarding.hint.' + step)}</small></span><small>{t(done[index] ? 'onboarding.ready' : index === 0 && state.value!.catalog.sources.length ? 'onboarding.modelsPending' : index === 1 && (state.configured || state.value!.agents.some(agent => agent.installed)) ? 'onboarding.pending' : 'onboarding.missing')}</small><ChevronRight size={16} /></button> })}</div>
  </section>
}
