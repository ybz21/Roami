import { useEffect, useRef, useState } from 'react'
import { modelSettingsHref } from '../settings/model-settings-route'
import { Button, Tabs } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { ModelCharges, chargeText } from '../settings/model-charges'
import type { Overview } from './AgentImprovement'
import PipelineRuns from './PipelineRuns'
import { RsiSettings } from './RsiSettings'
import { RsiOperationError } from './RsiOperationError'
import './rsi-workspace.css'

export function RsiWorkspace({ value, runId, onRun, node, refresh, failed = false }: { failed?: boolean; value: Overview; runId: string; onRun?: (id: string) => void; node: string | null; refresh: () => void }) {
  const { t, locale } = useI18n()
  const [view, setView] = useState(runId ? 'runs' : 'overview'), [selectedRun, setSelectedRun] = useState(runId)
  const [dirty, setDirty] = useState(false), [busy, setBusy] = useState(''), [error, setError] = useState('')
  const mounted = useRef(true), running = useRef(false), pending = useRef<Record<string, string>>({})
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { if (runId) { setSelectedRun(runId); setView('runs') } }, [runId])
  useEffect(() => { delete pending.current.formal }, [value.preferences.revision])
  useEffect(() => { delete pending.current.diagnostic }, [value.pipeline?.settings.revision])
  const openRun = (id: string) => { setSelectedRun(id); setView('runs'); onRun?.(id) }
  const run = async (kind: string) => {
    if (running.current || dirty) return
    running.current = true
    setBusy(kind); setError(''); pending.current[kind] ||= crypto.randomUUID()
    try {
      if (kind === 'diagnostic') {
        const response = await api('POST', '/agent/improvement/pipeline/requests', { request_key: pending.current[kind] })
        if (!mounted.current) return
        openRun(response.data.id)
      } else if (kind === 'formal') {
        for (const machine_id of value.preferences.machine_ids) {
          if (!mounted.current) return
          await api('POST', '/agent/improvement/requests', { machine_id, request_key: pending.current[kind] })
        }
        if (mounted.current) { setSelectedRun(''); setView('runs') }
      } else if (kind === 'prepare') {
        await api('POST', '/agent/improvement/prepare')
      } else {
        await api('POST', '/agent/improvement/machines', { id: 'local-container', label: t('agent.rsi.localMachine'), mode: 'container' })
      }
      if (mounted.current) { delete pending.current[kind]; refresh() }
    } catch (e: any) { if (mounted.current) setError(e.apiError?.code || 'RSI_OPERATION_FAILED') }
    finally { running.current = false; if (mounted.current) setBusy('') }
  }
  const latest = value.pipeline!.runs[0], billing = value.billing
  const ready = !!value.preferences.suite_id && value.preferences.machine_ids.length > 0
  const date = (timestamp: number) => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(timestamp)
  return <div className="agent-rsi rsi-workspace">
    {dirty && view !== 'settings' && <div className="agent-rsi-actions" role="status"><span>{t('agent.experiment.unsaved')}</span><button type="button" className="tt-act" onClick={() => setView('settings')}>{t('agent.rsi.settingsTab')}</button></div>}
    {failed && <p className="agent-rsi-error" role="alert">{t('agent.rsi.loadFailed')} <Button onClick={refresh}>{t('agent.rsi.retry')}</Button></p>}
    <RsiOperationError code={error} />
    <Tabs activeKey={view} onChange={setView} items={[
      { key: 'overview', label: t('agent.rsi.overviewTab'), children: <div className="rsi-overview">
        <section className="rsi-budget"><div className="agent-rsi-heading"><h3>{t('agent.rsi.sharedBudget')}</h3><a className="tt-act" href={modelSettingsHref('proxy')}>{t('agent.rsi.modelSettings')}</a></div>
          {billing && <div className="agent-proxy-totals"><div><span>{t('agent.proxy.todayCost')}</span><strong><ModelCharges charges={billing.charges} localCharges={billing.localCharges} estimatedCharges={[]} incomplete={billing.unknown > 0 || billing.pending > 0} /></strong></div><div><span>{t('agent.proxy.dailyLimit')}</span><strong>{billing.dailyLimit === null ? t('agent.proxy.unlimited') : chargeText([{ currency: billing.currency, amount: String(billing.dailyLimit) }], locale)}</strong></div></div>}
          <p className="agent-rsi-muted">{t('agent.rsi.sharedBudgetHint')}</p>
        </section>
        <section className="agent-rsi-section"><div className="agent-rsi-heading"><h3>{t('agent.rsi.startEvaluation')}</h3><span className="agent-rsi-muted">{t(value.preferences.enabled ? 'agent.rsi.scheduleEnabled' : 'agent.rsi.scheduleDisabled', { hour: value.preferences.hour, timezone: value.preferences.timezone })}</span></div>
          <div className="agent-rsi-actions"><Button type="primary" disabled={dirty || !!busy || !ready} loading={busy === 'formal'} onClick={() => void run('formal')}>{t('agent.rsi.runFormal')}</Button><Button disabled={dirty || !!busy || !ready} loading={busy === 'diagnostic'} onClick={() => void run('diagnostic')}>{t('agent.pipeline.startTen')}</Button></div>
          {!ready && <div className="agent-rsi-actions"><span className="agent-rsi-muted">{t('agent.rsi.setupHint')}</span><Button disabled={!!busy} onClick={() => setView('settings')}>{t('agent.rsi.settingsTab')}</Button>{!value.catalog.suites.length && <Button loading={busy === 'prepare'} disabled={!!busy} onClick={() => void run('prepare')}>{t('agent.rsi.prepare')}</Button>}{!value.catalog.machines.length && <Button loading={busy === 'machine'} disabled={!!busy} onClick={() => void run('machine')}>{t('agent.rsi.addLocal')}</Button>}</div>}
        </section>
        <section className="agent-rsi-section"><div className="agent-rsi-heading"><h3>{t('agent.rsi.latestRun')}</h3>{latest && <span>{t('agent.pipeline.runState.' + latest.state)}</span>}</div>
          {latest ? <><button type="button" className="agent-rsi-cycle" onClick={() => openRun(latest.id)}><span>{t('agent.pipeline.mode.' + latest.mode)}<small>{date(latest.created_ms)}</small></span><span>{t('agent.pipeline.viewRun')}</span></button>{latest.summary && typeof latest.summary.passed === 'number' && <p className="agent-rsi-muted">{t('agent.rsi.latestResult', { passed: latest.summary.passed, total: latest.summary.cases ?? 0 })}</p>}</> : <p className="agent-rsi-muted">{t('agent.pipeline.noRuns')}</p>}
        </section>
        <details className="agent-rsi-section rsi-advanced"><summary>{t('agent.pipeline.localIssues')}</summary><PipelineRuns data={value.pipeline} view="issues" node={node} onRun={openRun} refresh={refresh} eligible={!dirty && ready} /></details>
      </div> },
      { key: 'runs', label: t('agent.experiment.runs'), children: <PipelineRuns data={value.pipeline} view={view === 'runs' ? 'runs' : ''} node={node} runId={selectedRun} onRun={openRun} refresh={refresh} eligible={!dirty && ready} /> },
      { key: 'settings', label: t('agent.rsi.settingsTab'), forceRender: true, children: <RsiSettings value={value} refresh={refresh} onDirtyChange={setDirty} disabled={!!busy} /> },
    ]} />
  </div>
}
