import React, { useState } from 'react'
import { ChevronRight, ClockIcon } from '../../../frontend/src/icons'
import SourceBinding from './okr-source-binding'
import { analyze, baselineText, bindMetrics, hasField, SetupDraft, starter } from './okr-setup-model'
import { format } from './prototype-data'

export const setupSteps = ['口述目标','确认 KR','分析指标','接入数据','预览看板','每日填报']
export default function OkrSetup({ draft, onChange, step, onStep, onComplete }: { draft: SetupDraft; onChange: (value: SetupDraft) => void; step: number; onStep: (value: number) => void; onComplete: () => void }) {
  const [error,setError] = useState('')
  const next = (value: number) => { setError(''); onStep(value) }
  const selected = new Set(draft.metrics.map(m => m.id))
  const bound = bindMetrics(draft).filter(m => m.bindingState === 'bound').length
  const editMetric = (id: string, change: Partial<import('./prototype-data').Metric>) => onChange({ ...draft, metricsConfirmed:false, candidates:draft.candidates.map(m => m.id === id ? { ...m,...change } : m), metrics:draft.metrics.map(m => m.id === id ? { ...m,...change } : m), keyResults: id === 'netFollowers' && change.target !== undefined ? draft.keyResults.map(kr => kr.id === 'growth' ? { ...kr,target:change.target! } : kr) : draft.keyResults })
  const changeSelection = (id: string, checked: boolean) => {
    const ids = new Set(selected)
    if (checked) { ids.add(id); if (id === 'netFollowers') ids.add('followers') }
    else { ids.delete(id); if (id === 'followers') ids.delete('netFollowers') }
    onChange({ ...draft, metrics: draft.candidates.filter(m => ids.has(m.id)), metricsConfirmed: false, binding: { ...draft.binding, status:'idle',sample:undefined } })
  }
  return <div className="form-page setup-page">
    <div className="tt-pagehead"><div><p className="eyebrow">第 {step + 1} 步，共 {setupSteps.length} 步</p><h1 className="desktop-only">{setupSteps[step]}</h1></div></div>
    <ol className="wizard-steps" aria-label="从 KR 分析指标并绑定来源的步骤">{setupSteps.map((label,index) => <li key={label} aria-current={step === index ? 'step' : undefined}><span>{index + 1}</span>{label}</li>)}</ol>
    {step === 0 && <>
      <p className="lead">先说方向，指标由 Roami 帮你分析。</p>
      <div className="choice-row">{[['creator','视频号','视频号涨粉'],['creator','抖音','抖音涨粉'],['repo','本机项目','项目维护']].map(([kind,platform,label]) => <button type="button" className="button" key={label} onClick={() => onChange(starter(kind as SetupDraft['kind'], platform))}>{label}</button>)}</div>
      <label className="field">口述内容<textarea rows={6} value={draft.statement} onChange={e => onChange({ ...draft,statement:e.target.value })} placeholder="例如：帮我提升抖音粉丝，持续分享 AI 编程……" /></label>
      <p className="meta">原型使用可编辑的分析示例，不要求你先报一组指标或知道接口地址。</p>
      <button type="button" className="button primary" onClick={() => {
        if (!draft.statement.trim()) return setError('先写下你想做到什么。')
        const kind = /repo|仓库|PocketBoard|性能/i.test(draft.statement) && !/视频号|抖音/.test(draft.statement) ? 'repo' : 'creator'
        const platform = /抖音/.test(draft.statement) ? '抖音' : '视频号'
        if (kind !== draft.kind || kind === 'creator' && platform !== draft.binding.platform) onChange({ ...starter(kind,platform),statement:draft.statement })
        next(1)
      }}>整理目标与 KR</button>
    </>}
    {step === 1 && <>
      <label className="field">大目标 O<input value={draft.title} onChange={e => onChange({ ...draft,title:e.target.value,metricsConfirmed:false })} /></label>
      <div className="form-grid"><label className="field">开始日期<input type="date" value={draft.start} onChange={e => onChange({ ...draft,start:e.target.value })} /></label><label className="field">结束日期<input type="date" value={draft.end} onChange={e => onChange({ ...draft,end:e.target.value })} /></label></div>
      <h3>希望得到哪些结果</h3><p className="meta">这些是结果草稿；下一步再分析用哪些指标衡量。建议值可修改，实际起点取样后建立。</p>
      {draft.keyResults.map((kr,index) => <section className="kr-editor" key={kr.id}><label className="check-row"><input type="checkbox" checked={kr.enabled} onChange={e => onChange({ ...draft,keyResults:draft.keyResults.map(old => old.id === kr.id ? { ...old,enabled:e.target.checked } : old),metricsConfirmed:false })} /><span>KR{index + 1} · {kr.title}</span></label><label className="field">结果描述<input value={kr.title} onChange={e => onChange({ ...draft,keyResults:draft.keyResults.map(old => old.id === kr.id ? { ...old,title:e.target.value } : old),metricsConfirmed:false })} /></label><label className="field">{kr.id === 'growth' ? '建议：本周期净增人数' : kr.id === 'engagement' ? '建议：近七日点赞量' : kr.id === 'retention' ? '建议：完播率（%）' : '结果目标'}<input type="number" min="1" value={kr.target} onChange={e => onChange({ ...draft,keyResults:draft.keyResults.map(old => old.id === kr.id ? { ...old,target:Number(e.target.value) } : old),metricsConfirmed:false })} /></label></section>)}
      <button type="button" className="button primary" onClick={() => {
        if (!draft.title.trim() || !draft.keyResults.some(kr => kr.enabled) || draft.keyResults.some(kr => kr.enabled && (!kr.title.trim() || kr.target <= 0))) return setError('至少选择一项结果，并填写描述和目标。')
        const candidates = analyze(draft)
        onChange({ ...draft,candidates,metrics:candidates,metricsConfirmed:false,binding:{ ...draft.binding,status:'idle',sample:undefined } });next(2)
      }}>从 KR 分析候选指标</button>
    </>}
    {step === 2 && <>
      <p className="lead">先确认衡量什么，再寻找数据。</p><p className="meta">一条 KR 可以对应多个指标；结果、派生与诊断指标分开解释，不都当作独立 KR 计分。</p>
      {draft.keyResults.filter(kr => kr.enabled).map(kr => <section className="metric-group" key={kr.id}><h2>{kr.title}</h2>{draft.candidates.filter(m => m.krId === kr.id).map(metric => <article className="candidate-metric" key={metric.id}><label className="check-row"><input type="checkbox" checked={selected.has(metric.id)} onChange={e => changeSelection(metric.id,e.target.checked)} /><span><b>{metric.name}</b><small>{metric.role ?? '结果'}指标 · {metric.channel} · {metric.window}</small></span></label><p>{metric.rationale ?? '用可验证结果观察这项 KR 是否实现。'}</p>{selected.has(metric.id) && <label className="field">指标名称<input value={metric.name} onChange={e => editMetric(metric.id,{ name:e.target.value })} /></label>}{selected.has(metric.id) && metric.id !== 'followers' && <label className="field">建议目标（{metric.unit}）<input type="number" min="0" max={metric.unit === '%' ? 100 : undefined} value={metric.target} onChange={e => editMetric(metric.id,{ target:Number(e.target.value) })} /></label>}<p className="meta">{metric.id === 'netFollowers' ? '计算：当前粉丝总量减有效起点。' : metric.id === 'rate' ? '计算：同窗口点赞量 / 有效播放量；后台口径需取样核对。' : metric.id === 'completion' ? '计算：同窗口完整播放量 / 有效播放量；后台口径需取样核对。' : `单位：${metric.unit}。实际基线待接入后建立。`}</p></article>)}</section>)}
      <p className="meta">已选 {draft.metrics.length} 个指标。此时不读取账号后台，也不会把建议来源显示为已绑定。</p>
      <button type="button" className="button primary" onClick={() => { if (!draft.metrics.length || draft.metrics.some(m => !m.name.trim() || !Number.isFinite(m.target) || m.target <= 0 || m.unit === '%' && m.target > 100)) return setError('至少保留一个有效指标，并核对名称与目标。'); onChange({ ...draft,metricsConfirmed:true });next(3) }}>确认这些指标，再寻找数据</button>
    </>}
    {step === 3 && <>
      <SourceBinding draft={draft} onChange={onChange} />
      <div className="form-actions"><button type="button" className="button primary" onClick={() => { onChange({ ...draft,metrics:bindMetrics(draft) });next(4) }}>{bound === draft.metrics.length ? '用已确认来源预览看板' : bound ? '保留未接入项，继续预览' : '先保留待接入指标，预览看板'}</button></div>
      <p className="meta">{bound}/{draft.metrics.length} 个指标已接上。未接入项不自动填数，可以稍后继续接入。</p>
    </>}
    {step === 4 && <>
      <label className="field">看板名称<input value={draft.boardTitle} onChange={e => onChange({ ...draft,boardTitle:e.target.value })} /></label>
      <div className="mapping-list">{draft.metrics.map(metric => <section className="mapping-row" key={metric.id}><span className="mapping-index">{draft.keyResults.find(kr => kr.id === metric.krId)?.title ?? '已确认 KR'}</span><div><h3>{metric.name}</h3><small>基线 {baselineText(metric)} · 目标 {format(metric.target,metric)}</small><small>{metric.source}</small><span className={`meta ${hasField(draft.binding,metric) ? 'ok-text' : 'warn-text'}`}>{hasField(draft.binding,metric) ? '已验证来源' : '待接入'}</span></div><ChevronRight size={18} /><span className="mapping-output">指标卡<small>日期对比与记录</small></span></section>)}</div>
      <label className="check-row"><input type="checkbox" checked={draft.showTrend} onChange={e => onChange({ ...draft,showTrend:e.target.checked })} /><span>显示趋势图<small>只展示实际观测，不生成未读取的历史。</small></span></label>
      <section className="board-preview"><h3>看板预览 · {draft.boardTitle}</h3><p className="meta">{draft.keyResults.filter(kr => kr.enabled).length} 条 KR / {draft.metrics.length} 个已确认指标 / {bound} 个已接入</p><div className="preview-metrics">{draft.metrics.map(metric => <div key={metric.id}><span>{metric.name}</span><strong>{hasField(draft.binding,metric) ? '等待写入有效观测' : '待接入'}</strong><small>{metric.window}</small></div>)}</div><div className="preview-axis"><ClockIcon size={16} /><span>确认的指标与来源决定看板，日期记录保留取样与更正。</span></div></section>
      <button type="button" className="button primary" onClick={() => next(5)}>确认看板，安排每日填报</button>
    </>}
    {step === 5 && <>
      <h2>{draft.boardTitle}</h2><p>{draft.metrics.length} 个指标已确认，{bound} 个已验证来源。</p>
      <label className="field">每天留给我的时间（分钟）<input type="number" min="10" max="240" value={draft.minutes} onChange={e => onChange({ ...draft,minutes:Number(e.target.value) })} /></label>
      <label className="check-row"><input type="checkbox" checked={draft.daily} onChange={e => onChange({ ...draft,daily:e.target.checked })} /><span>每天 21:00 更新可读取的指标<small>未接入、登录失效或字段缺失的项保持待处理，不用其他账号或推测值补数。</small></span></label>
      <p className="meta">{draft.binding.status === 'bound' ? '核对后的样本可作为首条记录；其余日期从后续有效读取积累。' : '可以先生成待接入看板，再从面板继续绑定来源。'}</p>
      <button type="button" className="button primary" onClick={onComplete}>{bound ? '生成看板并开始推进' : '生成待接入看板'}</button>
    </>}
    {error && <p className="error-text" role="alert">{error}</p>}
  </div>
}
