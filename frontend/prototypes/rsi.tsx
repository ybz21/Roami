import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { App as AntApp, Button, InputNumber, Modal, Radio, Select, Switch } from 'antd'
import { I18nProvider, useI18n } from '../src/i18n'
import { ThemeProvider, useThemeMode } from '../src/theme'
import { useLayout } from '../src/layout'
import { AppsIcon, BellIcon, ChevronLeft, ChevronRight, ClockIcon, FolderIcon, GearIcon, HomeIcon, PlayIcon } from '../src/icons'
import RsiRunResults from './rsi-run-results'
import { initialResultsView } from './rsi-run-history'
import type { WorkflowArtifact, WorkflowStage } from './rsi-workflow'
import '../src/index.css'
import '../src/mobile-material.css'
import './rsi.css'

// Preference writes stay inside the isolated prototype.
window.fetch = async () => new Response(JSON.stringify({ data: {} }), { headers: { 'Content-Type': 'application/json' } })
type Scenario = 'attention' | 'running' | 'complete' | 'empty' | 'limit' | 'unknown' | 'repairing'
type Route = 'overview' | 'workflow' | 'issues' | 'settings' | 'models' | 'artifact'
type Configuration = { schedule: boolean; hour: number; zone: string; suite: string; machine: string; repair: boolean; issue: boolean }
const initial: Configuration = { schedule: false, hour: 9, zone: 'Asia/Shanghai', suite: 'full', machine: 'local', repair: true, issue: false }
function Prototype() {
  const { t: translate, setLocale, locale } = useI18n()
  const t = (key: string, vars?: Record<string, string | number>) => translate('agent.rsiPrototype.' + key, vars)
  const resultText = (key: string) => translate('agent.rsiResults.' + key)
  const { setMode } = useThemeMode(), { phone } = useLayout()
  const { message } = AntApp.useApp(), [modal, contextHolder] = Modal.useModal()
  const [scenario, setScenario] = useState<Scenario>('attention'), [route, setRoute] = useState<Route>('overview')
  const [results, setResults] = useState(initialResultsView), [demoRun, setDemoRun] = useState(false)
  const [stopped, setStopped] = useState(false)
  const [config, setConfig] = useState<Configuration>(initial), [draft, setDraft] = useState(initial)
  const [limit, setLimit] = useState<number | null>(50), [limitDraft, setLimitDraft] = useState<number | null>(50)
  const [startOpen, setStartOpen] = useState(false), [runMode, setRunMode] = useState('full')
  const [returnRoute, setReturnRoute] = useState<Route>('overview'), [artifactOrigin, setArtifactOrigin] = useState<Route>('overview')
  const [simulateFailure, setSimulateFailure] = useState(false), [saveError, setSaveError] = useState(false)
  const [progress, setProgress] = useState(18), [spent, setSpent] = useState(12.8)
  const [workflowStage, setWorkflowStage] = useState<WorkflowStage | null>(null), [artifact, setArtifact] = useState<WorkflowArtifact | null>(null)
  const dirty = JSON.stringify(draft) !== JSON.stringify(config)
  const state = useRef({ setMode, setLocale }); state.current = { setMode, setLocale }
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source !== window.parent || event.data?.type !== 'rsi-prototype-settings') return
      if (typeof event.data.saveFailure === 'boolean') setSimulateFailure(event.data.saveFailure)
      if (event.data.theme) state.current.setMode(event.data.theme)
      if (event.data.locale) state.current.setLocale(event.data.locale)
      if (event.data.scenario) {
        setScenario(event.data.scenario); setStopped(false); setWorkflowStage(null); setRoute('overview'); setProgress(18); setRunMode('full'); setDemoRun(false)
        setResults({ ...initialResultsView, runId: ['running', 'limit', 'unknown'].includes(event.data.scenario) ? 'R06' : 'R04' })
        setSpent(event.data.scenario === 'limit' ? 50 : 12.8)
        if (event.data.scenario === 'limit') { setLimit(50); setLimitDraft(50) }
      }
    }
    window.addEventListener('message', receive)
    window.parent.postMessage({ type: 'rsi-prototype-ready' }, '*')
    return () => window.removeEventListener('message', receive)
  }, [])
  useEffect(() => {
    if (scenario !== 'running') return
    const timer = window.setInterval(() => setProgress(value => Math.min(value + 3, runMode === 'quick' ? 10 : 60)), 1800)
    return () => clearInterval(timer)
  }, [scenario, runMode])
  useEffect(() => { if (scenario === 'running' && progress >= (runMode === 'quick' ? 10 : 60)) { setDemoRun(true); setScenario('attention'); void message.success(t('done')) } }, [progress, scenario, runMode])
  const money = (value: number) => new Intl.NumberFormat(locale, { style: 'currency', currency: 'CNY', maximumFractionDigits: 2 }).format(value)
  const budgetText = t('budgetStatus', { spent: money(spent), limit: limit == null ? t('limitEmpty') : money(limit) })
  const blocked = scenario === 'limit' || scenario === 'unknown', top = ['workflow', 'overview', 'issues'].includes(route)
  const go = (next: Route) => { setRoute(next); setSaveError(false) }
  const openModels = () => { if (route === 'models') return; setReturnRoute(route); setLimitDraft(limit); go('models') }
  const openSettings = () => { setDraft(config); go('settings') }
  const back = () => {
    const destination = route === 'models' ? returnRoute : route === 'artifact' ? artifactOrigin : 'overview'
    if (route === 'settings' && dirty || route === 'models' && limit !== limitDraft) modal.confirm({ title: t('discard'), okText: t('discardAction'), cancelText: t('keepEditing'), onOk: () => { setDraft(config); setLimitDraft(limit); go(destination) } })
    else go(destination)
  }
  const begin = () => { setStopped(false); setWorkflowStage(null); setProgress(0); setDemoRun(true); setResults({ ...initialResultsView, runId: 'R06', baselineId: 'R04' }); setStartOpen(false); setScenario('running'); go('overview'); void message.success(t('demoStart')) }
  const stop = () => modal.confirm({ title: t('stop'), okText: t('stop'), cancelText: t('cancel'), onOk: () => { setStopped(true); setDemoRun(true); setScenario('attention'); void message.info(t('stopped')) } })
  const save = () => {
    if (simulateFailure) { setSaveError(true); return }
    if (route === 'settings') setConfig(draft)
    else { setLimit(limitDraft); if (scenario === 'limit' && (limitDraft == null || limitDraft > spent)) setScenario('attention') }
    void message.success(t('saved')); go(route === 'models' ? returnRoute : 'overview')
  }
  const openArtifact = (value: WorkflowArtifact) => { setArtifactOrigin(route); setArtifact(value); go('artifact') }
  const budgetNote = <div className="rsi-budget-note"><span><strong>{t('dailyBudget')}</strong><small>{budgetText}</small></span><button type="button" className="tt-act" onClick={openModels}>{t('modelPage')}<ChevronRight size={14} /></button></div>
  return <div className="rsi-prototype">
    {contextHolder}
    {!phone && <aside className="rsi-nav"><div className="rsi-brand"><AppsIcon size={22} /><strong>Roami</strong></div><p className="rsi-nav-caption">{t('settingsNav')}</p><nav aria-label={t('settingsNav')}>{[['settingsGeneral', HomeIcon], ['settingsModels', AppsIcon], ['settingsRsi', ClockIcon], ['settingsOther', BellIcon]].map(([name, Icon]) => <button type="button" key={String(name)} className={(name === 'settingsModels' ? route === 'models' : name === 'settingsRsi' && route !== 'models') ? 'selected' : ''} onClick={() => name === 'settingsModels' ? openModels() : name === 'settingsRsi' ? (route === 'settings' || route === 'models' ? back() : go('overview')) : void message.info(t('navigationHint'))}>{React.createElement(Icon as typeof HomeIcon, { size: 18 })}{t(String(name))}</button>)}</nav><small className="rsi-demo-caption">{t('badge')}</small></aside>}
    <main className="rsi-main">
      <header className={'tt-pagehead rsi-pagehead ' + (!top ? 'rsi-return-head' : '')}>
        {!top && <button type="button" className="rsi-back" aria-label={t('back')} onClick={back}><ChevronLeft size={20} /></button>}
        <div className="ttl"><h2>{t(top ? 'title' : route === 'settings' ? 'settings' : route === 'models' ? 'modelTitle' : 'artifactTitle')}</h2></div>
        {top && <div className="acts"><Button icon={<GearIcon size={17} />} aria-label={t('settings')} onClick={openSettings}>{!phone && t('settings')}</Button><Button type="primary" icon={<PlayIcon size={13} />} disabled={scenario === 'running'} onClick={() => setStartOpen(true)}>{t('run')}</Button></div>}
      </header>
      {top && <nav className="rsi-tabs" role="tablist" aria-label={t('title')}>{(['workflow', 'overview', 'issues'] as const).map((tab, index, tabs) => <button type="button" role="tab" key={tab} id={'rsi-tab-' + tab} aria-selected={route === tab} aria-controls={'rsi-panel-' + tab} tabIndex={route === tab ? 0 : -1} onClick={() => go(tab)} onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
        event.preventDefault()
        const next = tabs[event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]
        go(next); document.getElementById('rsi-tab-' + next)?.focus()
      }}>{resultText(tab === 'workflow' ? 'workflowTab' : tab === 'overview' ? 'runResults' : 'issueTab')}</button>)}</nav>}
      <div className="rsi-scroll" key={route} role={top ? 'tabpanel' : undefined} id={top ? 'rsi-panel-' + route : undefined} aria-labelledby={top ? 'rsi-tab-' + route : undefined} tabIndex={top ? 0 : undefined}><div className={'rsi-content' + (top ? ' rsi-content-results' : '')}>
        {top && <>
          {blocked && <div className="rsi-notice" role="status"><span className="rsi-row-copy"><strong>{t(scenario === 'limit' ? 'limitReached' : 'usageUnknown')}</strong><small>{t(scenario === 'limit' ? 'limitHint' : 'usageUnknownHint')}</small></span><Button onClick={openModels}>{t('goModels')}</Button></div>}
          <RsiRunResults view={route} scenario={scenario} progress={progress} mode={runMode} demoRun={demoRun} stopped={stopped} onStop={stop} state={results} setState={setResults} workflowStage={workflowStage} onStage={setWorkflowStage} onArtifact={openArtifact} onView={go} />
        </>}
          {route === 'settings' && <>
            <section className="rsi-section"><div className="rsi-setting-toggle"><span><strong>{t('schedule')}</strong><small>{t('scheduleHint')}</small></span><Switch checked={draft.schedule} aria-label={t('schedule')} onChange={schedule => setDraft({ ...draft, schedule })} /></div>{draft.schedule && <div className="rsi-form-grid"><label>{t('hour')}<Select aria-label={t('hour')} value={draft.hour} options={Array.from({ length: 24 }, (_, value) => ({ value, label: String(value).padStart(2, '0') + ':00' }))} onChange={hour => setDraft({ ...draft, hour })} /></label><label>{t('timezone')}<Select aria-label={t('timezone')} value={draft.zone} options={['Asia/Shanghai', 'Asia/Tokyo', 'UTC'].map(value => ({ value, label: value }))} onChange={zone => setDraft({ ...draft, zone })} /></label></div>}</section>
            <section className="rsi-section"><h3>{t('scope')}</h3><div className="rsi-form-grid"><label>{t('suite')}<Select aria-label={t('suite')} value={draft.suite} options={[{ value: 'full', label: t('suiteFull') }]} onChange={suite => setDraft({ ...draft, suite })} /></label><label>{t('machine')}<Select aria-label={t('machine')} value={draft.machine} options={[{ value: 'local', label: t('local') }]} onChange={machine => setDraft({ ...draft, machine })} /></label></div></section>
            <section className="rsi-section"><h3>{t('workflow')}</h3><div className="rsi-setting-toggle"><span><strong>{t('autoRepair')}</strong><small>{t('repairHint')}</small></span><Switch checked={draft.repair} aria-label={t('autoRepair')} onChange={repair => setDraft({ ...draft, repair })} /></div><div className="rsi-setting-toggle"><span><strong>{t('autoIssue')}</strong><small>{t('issueHint')}</small></span><Switch checked={draft.issue} aria-label={t('autoIssue')} onChange={issue => setDraft({ ...draft, issue })} /></div></section>
            <section className="rsi-section"><h3>{t('modelsBudget')}</h3><p className="rsi-muted">{t('inherit')}</p>{budgetNote}</section>
          </>}
          {route === 'models' && <>
            <section className="rsi-section"><p className="rsi-muted">{t('modelNote')}</p><div className="rsi-model-roles">{(['main', 'worker', 'memory'] as const).map(role => <div key={role}><span>{t('role.' + role)}</span><strong>{t('followingModel')}</strong></div>)}</div></section>
            <section className="rsi-section"><h3>{t('limit')}</h3><p className="rsi-muted">{t('budgetScope')}</p><div className="rsi-form-grid"><label>{t('limit')}<InputNumber aria-label={t('limit')} value={limitDraft} min={0.01} max={1000000} placeholder={t('limitEmpty')} onChange={value => setLimitDraft(value)} /></label><label>{t('limitCurrency')}<Select value="CNY" aria-label={t('limitCurrency')} options={[{ value: 'CNY', label: t('currency') }]} /></label></div><p className="rsi-footnote">{t('costRule')}</p></section><section className="rsi-section"><div className="rsi-section-heading"><h3>{t('spent')}</h3><strong>{money(spent)}</strong></div>{scenario === 'unknown' && <p className="rsi-muted">{t('usageUnknownHint')}</p>}</section>
          </>}
          {route === 'artifact' && artifact && <section className="rsi-section"><h3>{artifact.name}</h3><div className="rsi-artifact-preview">{artifact.text}</div></section>}
      </div></div>
      {(route === 'settings' || route === 'models') && <footer className="rsi-savebar"><div>{saveError ? <span role="alert" className="rsi-danger">{t('failureRecovery')}</span> : <span className="rsi-muted">{(route === 'settings' ? dirty : limitDraft !== limit) ? t('unsaved') : ''}</span>}</div><Button onClick={back}>{t('cancel')}</Button><Button type="primary" disabled={route === 'settings' ? !dirty : limitDraft === limit} onClick={save}>{t('save')}</Button></footer>}
      {phone && <nav className="rsi-bottom-nav" aria-label={t('mainNav.settings')}>{[['home', HomeIcon], ['projects', FolderIcon], ['tools', AppsIcon], ['settings', GearIcon]].map(([name, Icon]) => <button type="button" key={String(name)} className={name === 'settings' ? 'selected' : ''} onClick={() => name === 'settings' ? (route === 'settings' || route === 'models' ? back() : go('overview')) : void message.info(t('navigationHint'))}>{React.createElement(Icon as typeof HomeIcon, { size: 20 })}<span>{t('mainNav.' + name)}</span></button>)}</nav>}
    </main>
    <Modal open={startOpen} title={t('startTitle')} okText={t(blocked ? 'goModels' : 'start')} cancelText={t('cancel')} onCancel={() => setStartOpen(false)} onOk={() => { if (blocked) { setStartOpen(false); openModels() } else begin() }}><Radio.Group className="rsi-run-options" value={runMode} onChange={event => setRunMode(event.target.value)}><Radio value="quick"><strong>{t('quick')} · {t('cases', { count: 10 })}</strong><small>{t('quickHint')}</small></Radio><Radio value="full"><strong>{t('full')} · {t('cases', { count: 60 })}</strong><small>{t('fullHint')}</small></Radio></Radio.Group><div className="rsi-modal-budget"><strong>{t(blocked ? scenario === 'unknown' ? 'usageUnknown' : 'limitReached' : 'dailyBudget')}</strong><p>{blocked ? t(scenario === 'unknown' ? 'usageUnknownHint' : 'limitHint') : budgetText}</p></div><p className="rsi-footnote">{t('demoNotice')}</p></Modal>
  </div>
}
createRoot(document.getElementById('root')!).render(<I18nProvider><ThemeProvider><AntApp><Prototype /></AntApp></ThemeProvider></I18nProvider>)
