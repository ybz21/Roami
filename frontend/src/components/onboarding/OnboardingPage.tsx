import { useEffect, useState } from 'react'
import { Alert, App, Button, Select, Spin } from 'antd'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { type AgentKind } from '../../agent-kind'
import { AgentCatalog } from '../capabilities/AgentCatalog'
import OnboardingModels from './OnboardingModels'
import OnboardingRoami from './OnboardingRoami'
import { NewProjectModal } from '../projects/Projects'
import { TaskComposer, type TaskComposerHandle } from '../sessions/TaskComposer'
import { useRef } from 'react'
import { onboardingChanged, steps, nextOnboardingStep, useOnboardingState, type OnboardingProject, type OnboardingStep } from './onboarding-state'
import ModuleGuide from './ModuleGuide'
import OnboardingChecklist from './OnboardingChecklist'
import { OnboardingProgress } from './OnboardingProgress'
import './onboarding.css'

export default function OnboardingPage({ sub, onNav, onLaunch, onSession }: { sub: string; onNav: (route: string) => void; onLaunch: (kind: AgentKind) => Promise<void>; onSession: (name: string) => void }) {
  const { t } = useI18n(), { phone } = useLayout(), { message } = App.useApp()
  const state = useOnboardingState(), [part, selected, section] = sub.split('/')
  const [created, setCreated] = useState<OnboardingProject | null>(null)
  const [mainReady, setMainReady] = useState(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const composer = useRef<TaskComposerHandle>(null)
  const tour = part === 'tour', step = steps.includes(part as OnboardingStep) ? part as OnboardingStep : null
  const project = created || state.value?.projects.find(item => item.key === state.progress.project) || state.value?.projects[0]
  const done = [state.hasModels, (step === 'agents' && selected === 'roami' ? mainReady : !!state.value?.models.verified) && state.readyAgents.length > 0, !!project, !!state.progress.completed]
  const navigate = (next: OnboardingStep) => { void state.change({ started: true, dismissed: false }); onNav('onboarding/' + next) }
  const continueSetup = () => navigate(state.value ? nextOnboardingStep(state.value, state.progress) : 'model')
  const leave = () => { void state.change({ started: true }); onNav('home') }
  const saveProject = (item: { key: string; dir: string; git: boolean; name?: string }) => {
    if (!mounted.current) return
    setCreated({ ...item, name: item.name || item.dir.split('/').filter(Boolean).pop() || item.dir })
    void state.change({ project: item.key, started: true }); onboardingChanged(); onNav('onboarding/task')
  }
  return <div className="onboarding-page">
    {step && <OnboardingProgress current={step} done={done} onSelect={navigate} />}
    <div className="onboarding-scroll">
      {tour ? <ModuleGuide selected={selected} onSelect={id => onNav('onboarding/tour/' + id)} onNav={onNav} /> : state.loading ? <Spin /> : state.failed ? <Alert type="error" message={t('onboarding.loadFailed')} action={<Button onClick={state.refresh}>{t('agent.retry')}</Button>} /> : !step ? <OnboardingChecklist force onNav={onNav} /> : <div className="onboarding-content">
        {!phone && <header className="tt-pagehead"><div className="ttl"><h2>{t('onboarding.step.' + step)}</h2></div></header>}
        {step === 'model' && <OnboardingModels sub={sub.split('/').slice(1).join('/')} onNav={onNav} />}
        {step === 'agents' && (selected === 'roami' ? <OnboardingRoami onNav={onNav} onReadyChange={setMainReady} /> : <><p>{t('onboarding.agentIntro')}</p><p className="onboarding-note">{t('onboarding.agentState')}</p><AgentCatalog embedded initialKind={selected} initialSection={section} mainVerified={!!state.value?.models.verified} onSelect={id => onNav('onboarding/agents' + (id ? '/' + id : ''))} onLaunch={onLaunch} /></>)}
        {step === 'project' && <><p>{t('onboarding.projectIntro')}</p><p className="onboarding-note">{t('onboarding.nodeDirectory')}</p>{!!state.value?.projects.length && <label className="onboarding-project-select">{t('onboarding.existingProject')}<Select aria-label={t('onboarding.chooseProject')} value={project?.key} options={state.value.projects.map(item => ({ value: item.key, label: item.name }))} onChange={key => { setCreated(null); void state.change({ project: key }); onNav('onboarding/task') }} /></label>}<NewProjectModal inline open onClose={() => {}} onCreated={saveProject} /></>}
        {step === 'task' && <>
          {!state.hasModels && <Alert type="warning" message={t('onboarding.modelsMissing')} action={<Button onClick={() => navigate('model')}>{t('onboarding.step.model')}</Button>} />}
          {!state.value?.models.verified && <Alert type="warning" message={t('onboarding.mainMissing')} action={<Button onClick={() => onNav('onboarding/agents/roami')}>{t('hub.roamiModels')}</Button>} />}
          {!state.readyAgents.length && <Alert type="warning" message={t('onboarding.agentMissing')} action={<Button onClick={() => navigate('agents')}>{t('onboarding.step.agents')}</Button>} />}
          {!project ? <Alert type="warning" message={t('onboarding.projectMissing')} action={<Button onClick={() => navigate('project')}>{t('onboarding.step.project')}</Button>} /> : <><div className="onboarding-project-identity"><strong>{project.name}</strong><code>{project.dir}</code></div>
            {state.progress.completed ? <Alert type="success" message={t('onboarding.submitted')} action={<Button onClick={() => onNav('projects/' + encodeURIComponent(project.key))}>{t('onboarding.showProject')}</Button>} /> : state.hasModels && state.readyAgents.length > 0 && state.value?.models.verified && <><TaskComposer ref={composer} key={project.key} dir={project.dir} isGit={project.git} openTerm={onSession} draftKey={'onboarding-task:' + project.dir} initialAgent={state.readyAgents[0].kind} onCreated={name => { void state.change({ completed: true, session: name, project: project.key }).then(ok => { if (!ok) message.error(t('onboarding.savingFailed')) }) }} /><button type="button" className="onboarding-suggestion" onClick={() => composer.current?.appendInstruction(t('onboarding.samplePrompt'))}><strong>{t('onboarding.sample')}</strong><small>{t('onboarding.sampleHint')}</small></button></>}
          </>}
        </>}
      </div>}
    </div>
    <footer className="onboarding-footer"><Button onClick={() => onNav(tour && selected ? 'onboarding/tour' : step === 'agents' && selected ? 'onboarding/agents' : 'home')}>{t(tour && selected ? 'onboarding.guide.back' : step === 'agents' && selected ? 'common.back' : 'onboarding.back')}</Button>
      {!tour && <Button type="text" onClick={() => onNav('onboarding/tour')}>{t('onboarding.readTour')}</Button>}
      {tour ? <Button type="primary" onClick={continueSetup}>{t(state.progress.started ? 'onboarding.continue' : 'onboarding.begin')}</Button> : step && step !== 'task' ? <><Button onClick={step === 'agents' ? () => navigate('project') : leave}>{t('onboarding.skip')}</Button><Button type="primary" disabled={!done[steps.indexOf(step)]} onClick={() => navigate(steps[steps.indexOf(step) + 1])}>{t('onboarding.next')}</Button></> : null}
    </footer>
  </div>
}
