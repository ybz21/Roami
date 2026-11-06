import type { ReactNode } from 'react'
import { Button, Checkbox, Input, InputNumber, Select } from 'antd'
import { useI18n } from '../../../i18n'
import { PlusIcon, TrashIcon } from '../../../icons'
import { dashboardOf, stableId, type Configuration, type DashboardWidget, type Initiative, type KeyResult, type Metric } from './okr-workspace'

export function OkrField({ label, children }: { label: string; children: ReactNode }) {
  return <label className="okr-field"><span>{label}</span>{children}</label>
}
export type SwarmOption = { id: string; name: string }

export default function OkrConfiguration({ value, onChange, onSave, onCancel, busy, swarms, swarmError, onLoadSwarms }: {
  value: Configuration; onChange: (value: Configuration) => void; onSave: () => void; onCancel?: () => void
  busy: boolean; swarms: SwarmOption[]; swarmError: boolean; onLoadSwarms: () => void
}) {
  const { t } = useI18n()
  const patch = (change: Partial<Configuration>) => onChange({ ...value, ...change })
  const metric = (id: string, change: Partial<Metric>) => patch({ metrics: value.metrics.map(m => m.id === id ? { ...m, ...change } : m) })
  const kr = (id: string, change: Partial<KeyResult>) => patch({ keyResults: value.keyResults.map(k => k.id === id ? { ...k, ...change } : k) })
  const initiative = (id: string, change: Partial<Initiative>) => patch({ initiatives: (value.initiatives || []).map(item => item.id === id ? { ...item, ...change } : item) })
  const dashboard = dashboardOf(value)
  const widget = (id: string, change: Partial<DashboardWidget>) => patch({ dashboard: { ...dashboard, widgets: dashboard.widgets.map(item => item.id === id ? { ...item, ...change } : item) } })
  const suggestions = () => {
    const stars = stableId('m'), forks = stableId('m'), interest = stableId('kr'), adoption = stableId('kr')
    patch({
      objective: t('okr.template.objective'), autoCollect: false,
      metrics: [
        { id: stars, name: t('okr.template.metric'), unit: '', source: 'github', repo: 'ybz21/Roami', field: 'stars' },
        { id: forks, name: t('okr.template.forks'), unit: '', source: 'github', repo: 'ybz21/Roami', field: 'forks' },
        { id: stableId('m'), name: t('okr.template.bilibiliCompletion'), unit: t('okr.unit.percent'), source: 'manual' },
        { id: stableId('m'), name: t('okr.template.bilibiliWatch'), unit: t('okr.unit.seconds'), source: 'manual' },
        { id: stableId('m'), name: t('okr.template.xClicks'), unit: '', source: 'manual' },
      ],
      keyResults: [
        { id: interest, title: t('okr.template.kr'), horizon: 'long', metricId: stars, target: 100, mode: 'increase', dueDate: value.endDate },
        { id: adoption, title: t('okr.template.forkKr'), horizon: 'long', metricId: forks, target: 20, mode: 'increase', dueDate: value.endDate },
      ],
      initiatives: [
        { id: stableId('initiative'), title: t('okr.template.xInitiative'), channel: 'x', keyResultIds: [interest], description: t('okr.template.xDescription'), acceptance: t('okr.template.xAcceptance') },
        { id: stableId('initiative'), title: t('okr.template.bilibiliInitiative'), channel: 'bilibili', keyResultIds: [interest, adoption], description: t('okr.template.bilibiliDescription'), acceptance: t('okr.template.bilibiliAcceptance') },
      ],
    })
  }
  return <form className="okr-form" onSubmit={e => { e.preventDefault(); onSave() }}>
    <fieldset disabled={busy}>
      {!value.objective && !value.metrics.length && <Button onClick={suggestions}>{t('okr.template.use')}</Button>}
      <OkrField label={t('okr.objective')}><Input.TextArea required value={value.objective} onChange={e => patch({ objective: e.target.value })} autoSize={{ minRows: 2, maxRows: 5 }} /></OkrField>
      <div className="okr-grid">
        <OkrField label={t('okr.startDate')}><input type="date" required value={value.startDate} onChange={e => patch({ startDate: e.target.value })} /></OkrField>
        <OkrField label={t('okr.endDate')}><input type="date" required min={value.startDate} value={value.endDate} onChange={e => patch({ endDate: e.target.value })} /></OkrField>
      </div>
      <h3>{t('okr.metrics')}</h3>
      {value.metrics.map(m => <section className="okr-editor-row" key={m.id}>
        <div className="okr-grid">
          <OkrField label={t('okr.metricName')}><Input required value={m.name} onChange={e => metric(m.id, { name: e.target.value })} /></OkrField>
          <OkrField label={t('okr.unit')}><Input value={m.unit} onChange={e => metric(m.id, { unit: e.target.value })} /></OkrField>
          <OkrField label={t('okr.source')}><Select disabled={busy} aria-label={t('okr.source')} value={m.source} onChange={source => metric(m.id, { source })} options={(['manual', 'github'] as const).map(source => ({ value: source, label: t('okr.source.' + source) }))} /></OkrField>
          {m.source === 'github' && <>
            <OkrField label={t('okr.repo')}><Input required value={m.repo || ''} placeholder={t('okr.repoPlaceholder')} onChange={e => metric(m.id, { repo: e.target.value })} /></OkrField>
            <OkrField label={t('okr.githubField')}><Select disabled={busy} aria-label={t('okr.githubField')} value={m.field} onChange={field => metric(m.id, { field })} options={['stars', 'forks'].map(field => ({ value: field, label: t('okr.github.' + field) }))} /></OkrField>
          </>}
        </div>
        <Button danger icon={<TrashIcon />} disabled={value.keyResults.some(k => k.metricId === m.id) || dashboard.html?.metricIds.includes(m.id)} onClick={() => patch({ metrics: value.metrics.filter(x => x.id !== m.id), ...(value.dashboard ? { dashboard: { ...value.dashboard, widgets: value.dashboard.widgets.map(item => ({ ...item, metricIds: item.metricIds?.filter(id => id !== m.id) })) } } : {}) })}>{t('okr.removeMetric')}</Button>
      </section>)}
      <Button icon={<PlusIcon />} onClick={() => patch({ metrics: [...value.metrics, { id: stableId('m'), name: '', unit: '', source: 'manual' }] })}>{t('okr.addMetric')}</Button>
      <h3>{t('okr.keyResults')}</h3>
      {value.keyResults.map(k => <section className="okr-editor-row" key={k.id}>
        <OkrField label={t('okr.krTitle')}><Input required value={k.title} onChange={e => kr(k.id, { title: e.target.value })} /></OkrField>
        <div className="okr-grid">
          <OkrField label={t('okr.horizon')}><Select disabled={busy} aria-label={t('okr.horizon')} value={k.horizon} onChange={horizon => kr(k.id, { horizon })} options={['long', 'short'].map(h => ({ value: h, label: t('okr.horizon.' + h) }))} /></OkrField>
          <OkrField label={t('okr.metric')}><Select disabled={busy} aria-label={t('okr.metric')} value={k.metricId || undefined} onChange={metricId => kr(k.id, { metricId })} options={value.metrics.map(m => ({ value: m.id, label: m.name || t('okr.unnamedMetric') }))} /></OkrField>
          <OkrField label={t('okr.mode')}><Select disabled={busy} aria-label={t('okr.mode')} value={k.mode} onChange={mode => kr(k.id, { mode })} options={['increase', 'atLeast', 'atMost'].map(mode => ({ value: mode, label: t('okr.mode.' + mode) }))} /></OkrField>
          <OkrField label={t('okr.target')}><InputNumber aria-label={t('okr.target')} required value={Number.isFinite(k.target) ? k.target : null} onChange={target => kr(k.id, { target: target === null ? NaN : target })} /></OkrField>
          <OkrField label={t('okr.dueDate')}><input type="date" required min={value.startDate} max={value.endDate} value={k.dueDate} onChange={e => kr(k.id, { dueDate: e.target.value })} /></OkrField>
        </div>
        <Button danger icon={<TrashIcon />} onClick={() => patch({ keyResults: value.keyResults.filter(x => x.id !== k.id), initiatives: value.initiatives?.map(item => ({ ...item, keyResultIds: item.keyResultIds.filter(id => id !== k.id) })), ...(value.dashboard ? { dashboard: { ...value.dashboard, widgets: value.dashboard.widgets.map(item => ({ ...item, keyResultIds: item.keyResultIds?.filter(id => id !== k.id) })) } } : {}) })}>{t('okr.removeKr')}</Button>
      </section>)}
      <Button icon={<PlusIcon />} onClick={() => patch({ keyResults: [...value.keyResults, { id: stableId('kr'), title: '', horizon: 'short', metricId: value.metrics[0]?.id || '', target: 1, mode: 'atLeast', dueDate: value.endDate }] })}>{t('okr.addKr')}</Button>
      <h3>{t('okr.initiatives')}</h3>
      <p className="okr-muted">{t('okr.initiativesHint')}</p>
      {(value.initiatives || []).map(item => <section className="okr-editor-row" key={item.id}>
        <div className="okr-grid">
          <OkrField label={t('okr.initiativeTitle')}><Input required value={item.title} onChange={e => initiative(item.id, { title: e.target.value })} /></OkrField>
          <OkrField label={t('okr.channel')}><Input required value={item.channel} placeholder={t('okr.channelPlaceholder')} onChange={e => initiative(item.id, { channel: e.target.value })} /></OkrField>
        </div>
        <OkrField label={t('okr.linkedResults')}><Select mode="multiple" disabled={busy} aria-label={t('okr.linkedResults')} value={item.keyResultIds} options={value.keyResults.map(result => ({ value: result.id, label: result.title || t('okr.unnamedResult') }))} onChange={keyResultIds => initiative(item.id, { keyResultIds })} /></OkrField>
        <OkrField label={t('okr.initiativeDescription')}><Input.TextArea value={item.description} onChange={e => initiative(item.id, { description: e.target.value })} autoSize={{ minRows: 2, maxRows: 5 }} /></OkrField>
        <OkrField label={t('okr.initiativeAcceptance')}><Input.TextArea value={item.acceptance} onChange={e => initiative(item.id, { acceptance: e.target.value })} autoSize={{ minRows: 2, maxRows: 5 }} /></OkrField>
        <Button danger icon={<TrashIcon />} onClick={() => patch({ initiatives: value.initiatives?.filter(row => row.id !== item.id) })}>{t('okr.removeInitiative')}</Button>
      </section>)}
      <Button icon={<PlusIcon />} onClick={() => patch({ initiatives: [...(value.initiatives || []), { id: stableId('initiative'), title: '', channel: '', keyResultIds: [], description: '', acceptance: '' }] })}>{t('okr.addInitiative')}</Button>
      <details className="okr-dashboard-config"><summary>{t('okr.dashboardConfiguration')}</summary>
        {dashboard.html ? <p className="okr-muted">{t('okr.html.editFiles')}</p> : <>{dashboard.widgets.map(item => <section className="okr-editor-row" key={item.id}>
          <div className="okr-grid">
            <OkrField label={t('okr.widgetTitle')}><Input value={item.title || ''} onChange={e => widget(item.id, { title: e.target.value })} /></OkrField>
            <OkrField label={t('okr.widgetType')}><Select disabled={busy} aria-label={t('okr.widgetType')} value={item.type} options={['keyResults', 'metricTrend', 'nextAction'].map(type => ({ value: type, label: t('okr.widget.' + type) }))} onChange={type => widget(item.id, { type })} /></OkrField>
          </div>
          {item.type === 'keyResults' && <OkrField label={t('okr.widgetResults')}><Select mode="multiple" disabled={busy} aria-label={t('okr.widgetResults')} value={item.keyResultIds || []} options={value.keyResults.map(result => ({ value: result.id, label: result.title }))} onChange={keyResultIds => widget(item.id, { keyResultIds })} /></OkrField>}
          {item.type === 'metricTrend' && <OkrField label={t('okr.widgetMetrics')}><Select mode="multiple" disabled={busy} aria-label={t('okr.widgetMetrics')} value={item.metricIds || []} options={value.metrics.map(metric => ({ value: metric.id, label: metric.name }))} onChange={metricIds => widget(item.id, { metricIds })} /></OkrField>}
          <Button danger icon={<TrashIcon />} onClick={() => patch({ dashboard: { ...dashboard, widgets: dashboard.widgets.filter(row => row.id !== item.id) } })}>{t('okr.removeWidget')}</Button>
        </section>)}
        <Button icon={<PlusIcon />} onClick={() => patch({ dashboard: { ...dashboard, widgets: [...dashboard.widgets, { id: stableId('widget'), type: 'metricTrend' }] } })}>{t('okr.addWidget')}</Button></>}
      </details>
      <h3>{t('okr.swarm')}</h3>
      <OkrField label={t('okr.swarm')}><Select disabled={busy} allowClear aria-label={t('okr.swarm')} value={value.swarm || undefined} onChange={swarm => patch({ swarm: swarm || '' })} options={swarms.map(s => ({ value: s.id, label: s.name }))} /></OkrField>
      {swarmError && <p role="alert">{t('okr.swarmLoadFailed')} <Button onClick={onLoadSwarms}>{t('inbox.retry')}</Button></p>}
      <p className="okr-muted">{t('okr.swarmHint')}</p>
      <Checkbox checked={value.autoCollect} onChange={e => patch({ autoCollect: e.target.checked })}>{t('okr.autoCollect')}</Checkbox>
      <p className="okr-muted">{t('okr.confirmSources')}</p>
      <div className="okr-actions">
        <Button type="primary" htmlType="submit" loading={busy}>{t('okr.save')}</Button>
        {onCancel && <Button onClick={onCancel}>{t('common.cancel')}</Button>}
      </div>
    </fieldset>
  </form>
}
