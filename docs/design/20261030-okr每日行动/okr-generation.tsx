import React, { useEffect, useRef, useState } from 'react'
import { CheckIcon, ChevronRight, FileTextIcon, TerminalIcon } from '../../../frontend/src/icons'
import { BrowserObservation, GeneratedKr, GeneratedMetric, GeneratedPlan, measuredValue, parsePlan, validateObservation } from './okr-generation-contract'
import { growthReplay, qualityReplay, replayObservation, replayOptions } from './okr-generation-replays'

export const generationSteps = ['理解目标','生成 KR','拆解指标与看板','生成连接方案','验证取数','按日运行']
const storageKey = 'roami-okr-generation-v1'
function restore(): { plan: GeneratedPlan | null; records: BrowserObservation[]; replayIndex: number; baseline: boolean; degraded: string[] } {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? 'null')
    const plan = saved?.plan ? parsePlan(JSON.stringify(saved.plan)) : null
    return { plan,records:plan ? saved.records.map((row: unknown) => validateObservation(row,plan)) : [],replayIndex:saved?.replayIndex === 1 ? 1 : 0,baseline:saved?.baseline === true,degraded:Array.isArray(saved?.degraded) ? saved.degraded.filter((id:unknown) => typeof id === 'string') : [] }
  } catch { return { plan:null,records:[],replayIndex:0,baseline:false,degraded:[] } }
}
const shown = (value: number | null, unit: string) => value === null ? '待取得有效数据' : `${Number(value.toFixed(2)).toLocaleString('zh-CN')}${unit}`
const previousDay = (date: string) => new Date(Date.parse(`${date}T12:00:00Z`) - 86400000).toISOString().slice(0,10)
function download(name: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{ type:'application/json' }))
  const link = document.createElement('a'); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url)
}
export function KrProposal({ kr, index }: { kr: GeneratedKr; index: number }) {
  return <article className={`generated-kr kr-${kr.view}`} data-kr-view={kr.view}>
    <p className="eyebrow">KR {index + 1} · {({ number:'数值结果',milestones:'阶段验收',checklist:'验收清单' })[kr.view]}</p>
    <h3>{kr.title}</h3>
    {kr.horizon && <p className="meta">{({long:'长期 KR',short:'短期 KR / 检查点',daily:'日结果'})[kr.horizon]}{kr.period ? ` · ${kr.period.start} 至 ${kr.period.end}` : ''}</p>}
    {kr.view === 'number' ? <p className="kr-target">{shown(kr.target ?? null,kr.unit ?? '')}<small>建议目标；达成依据独立观测</small></p> : <ol className="generated-items">{kr.items?.map(item => <li key={item}>{item}</li>)}</ol>}
    <p className="meta">{kr.rationale}</p>
  </article>
}
export function DateTrend({ metric, records }: { metric: GeneratedMetric; records: BrowserObservation[] }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const el = canvas.current!
    const draw = () => {
      const rect = el.getBoundingClientRect(), scale = devicePixelRatio || 1
      el.width = rect.width * scale; el.height = rect.height * scale
      const ctx = el.getContext('2d')!; ctx.scale(scale,scale)
      const css = getComputedStyle(document.documentElement)
      const values = records.filter(r => r.connectorId === metric.connectorId).sort((a,b) => a.date.localeCompare(b.date)).map(r => ({ date:r.date,value:measuredValue(metric,records,r.date) }))
      ctx.fillStyle = css.getPropertyValue('--text-dim'); ctx.font = `${css.getPropertyValue('--fs-meta')} system-ui`
      if (!values.length || values.every(p => p.value === null)) { ctx.fillText('没有有效历史，不生成曲线。',16,48); return }
      const valid = values.flatMap(p => p.value === null ? [] : [p.value]), min = Math.min(...valid), max = Math.max(...valid), span = Math.max(max - min,1)
      const x = (i:number) => 24 + i * (rect.width - 64) / Math.max(1,values.length - 1)
      const y = (v:number) => rect.height - 48 - (v - min) / span * (rect.height - 80)
      ctx.strokeStyle = css.getPropertyValue('--accent'); ctx.lineWidth = 2; ctx.beginPath()
      let connected = false
      values.forEach((p,i) => { if (p.value === null) { connected = false;return }; if (connected) ctx.lineTo(x(i),y(p.value));else ctx.moveTo(x(i),y(p.value));connected = true });ctx.stroke()
      values.forEach((p,i) => { if (p.value === null) return; ctx.fillStyle = css.getPropertyValue('--accent'); ctx.beginPath();ctx.arc(x(i),y(p.value),4,0,Math.PI*2);ctx.fill();ctx.fillStyle = css.getPropertyValue('--text-dim');ctx.fillText(p.date.slice(5),x(i)-16,rect.height-12);ctx.fillText(String(Number(p.value.toFixed(2))),x(i)-12,y(p.value)-12) })
    }
    draw();const observer = new ResizeObserver(draw);observer.observe(el)
    const theme = new MutationObserver(draw);theme.observe(document.documentElement,{ attributes:true,attributeFilter:['data-theme'] })
    return () => { observer.disconnect();theme.disconnect() }
  },[metric,records])
  return <canvas className="generated-trend" ref={canvas} role="img" aria-label={`${metric.name}日期趋势，数值与来源见日期记录`} />
}
export default function OkrGeneration({ step, onStep }: { step: number; onStep: (step: number) => void }) {
  const [initial] = useState(restore)
  const [plan,setPlan] = useState(initial.plan)
  const [oldPlan,setOldPlan] = useState<GeneratedPlan|null>(null)
  const [records,setRecords] = useState(initial.records)
  const [replayIndex,setReplayIndex] = useState(initial.replayIndex)
  const [statement,setStatement] = useState(initial.plan?.statement ?? growthReplay.statement)
  const [response,setResponse] = useState('')
  const [error,setError] = useState('')
  const [status,setStatus] = useState('')
  const [scenario,setScenario] = useState('ready')
  const [degraded,setDegraded] = useState<string[]>(initial.degraded)
  const [date,setDate] = useState(initial.records.at(-1)?.date ?? '2026-11-11')
  const [baseline,setBaseline] = useState(initial.baseline)
  const [feedback,setFeedback] = useState('')
  const heading = useRef<HTMLDivElement>(null)
  useEffect(() => { try { localStorage.setItem(storageKey,JSON.stringify({ plan,records,replayIndex,baseline,degraded })) } catch {} },[plan,records,replayIndex,baseline,degraded])
  useEffect(() => { setError('');setStatus('');requestAnimationFrame(() => heading.current?.scrollIntoView({ block:'start' })) },[step])
  const activeStep = plan ? step : 0
  const sourceRecords = records.filter(r => r.date === date)
  const effective: GeneratedPlan|null = plan ? { ...plan,metrics:plan.metrics.map(m => {
    if (!baseline || m.formula.op !== 'difference' || m.formula.baseline !== null) return m
    const row = records.find(r => r.connectorId === m.connectorId && r.date === previousDay(plan.cycleStart))
    return row ? { ...m,formula:{ ...m.formula,baseline:row.values[m.formula.field]?.value ?? null } } : m
  }) } : null
  function apply(next: GeneratedPlan) {
    setOldPlan(plan);setPlan(parsePlan(JSON.stringify(next)));setStatement(next.statement);setRecords([]);setDegraded([]);setBaseline(false);setError('');setStatus('');onStep(1)
  }
  function importPlan() { try { apply(parsePlan(response)) } catch(e) { setError(e instanceof Error ? e.message : '无法读取方案。') } }
  function acceptSample(input: unknown) {
    try {
      const row = validateObservation(input,plan!)
      const existing = records.find(old => old.connectorId === row.connectorId && old.date === row.date)
      const fieldIds = [...new Set([...Object.keys(existing?.values ?? {}),...Object.keys(row.values)])]
      if (existing && fieldIds.some(id => existing.values[id]?.value !== row.values[id]?.value || existing.values[id]?.unit !== row.values[id]?.unit)) { setError('这个来源和日期已有不同记录。本演示保留原值，请换一个日期验证。');return }
      if (existing) { setDegraded(old => old.filter(id => id !== row.connectorId));setError('');setStatus('同一账号与日期复验通过；保留原记录，不重复写入。');return }
      setRecords(old => [...old,row].sort((a,b) => a.date.localeCompare(b.date)));setDate(row.date);setDegraded(old => old.filter(id => id !== row.connectorId));setError('');setStatus(`已核对 ${row.accountId} / ${row.date}；${row.evidenceKind === 'replay' ? '响应回放样本' : '本地浏览器夹具样本'}。`)
    } catch(e) { setError(e instanceof Error ? e.message : '样本校验失败。') }
  }
  const readFile = (event: React.ChangeEvent<HTMLInputElement>, consume: (value:string) => void) => {
    const file = event.target.files?.[0]
    if (!file) return
    if (file.size > 100000) { setError('文件过大，请导入单次响应或样本。');return }
    file.text().then(consume).catch(() => setError('读取文件失败，请重试。'));event.target.value = ''
  }
  return <div className="generation-page" ref={heading}>
    <div className="tt-pagehead"><div><p className="eyebrow">由智能体提出方案，由证据连接数据</p><h1 className="desktop-only">动态生成 OKR</h1><p>目标、KR、指标、连接方式和看板逐步形成。</p></div></div>
    <p className="generation-mode">响应回放 · 未接入实时模型</p>
    <ol className="generation-nav" aria-label="动态构建过程">{generationSteps.map((label,index) => <li key={label} aria-current={index === activeStep ? 'step' : undefined}><span>{index + 1}</span>{label}</li>)}</ol>
    {activeStep === 0 && <section className="generation-section">
      <p className="lead">你说方向，智能体提出怎样才算做到。</p>
      <div className="choice-row">{replayOptions.map((option,index) => <button type="button" className={`button ${replayIndex === index ? 'selected' : ''}`} key={option.label} aria-pressed={replayIndex === index} onClick={() => { setReplayIndex(index);setStatement(option.plan.statement);setError('') }}>{option.label}回放</button>)}</div>
      <label className="field">我的目标<textarea rows={4} value={statement} onChange={e => setStatement(e.target.value)} /></label>
      <button type="button" className="button primary" onClick={() => { if (statement !== replayOptions[replayIndex].plan.statement) { setError('这段目标还没有模型响应。请导入对应方案；不会把新目标偷偷套入示例。');return };apply(replayOptions[replayIndex].plan) }}>回放智能体如何拆解</button>
      <p className="meta">新目标可导入对应模型响应；浏览器读取可在本地夹具执行。</p>
    </section>}
    {activeStep === 1 && plan && <>
      <section className="generation-section"><p className="eyebrow">智能体的分析摘要</p><h2>{plan.objective}</h2><p>{plan.rationale}</p><details><summary>{plan.assumptions.length} 项待确认假设</summary><ul>{plan.assumptions.map(item => <li key={item}>{item}</li>)}</ul></details></section>
      {oldPlan && <section className="generation-diff" aria-label="本次方案变化"><h3>根据新信息调整方案</h3><p>KR 从 {oldPlan.keyResults.length} 条变为 {plan.keyResults.length} 条；指标从 {oldPlan.metrics.length} 个变为 {plan.metrics.length} 个。</p><p className="meta">{plan.keyResults.filter(kr => !oldPlan.keyResults.some(old => old.id === kr.id)).map(kr => `新增：${kr.title}`).join('；') || '请核对结果描述、口径和组件变化。'} 原数据不自动迁入新口径。</p></section>}
      <div className="generated-krs">{plan.keyResults.map((kr,index) => <KrProposal key={kr.id} kr={kr} index={index} />)}</div>
      <div className="form-actions"><button type="button" className="button primary" onClick={() => onStep(2)}>采用这些 KR，继续拆解</button>{plan.statement === growthReplay.statement && <button type="button" className="button" onClick={() => apply(qualityReplay)}>回放补充：也看点赞率和发布验收</button>}</div>
      <details className="generation-section"><summary>补充或纠正目标</summary><label className="field">补充内容<textarea value={feedback} onChange={e => setFeedback(e.target.value)} rows={3} /></label><button type="button" className="button" onClick={() => setStatus(feedback.trim() ? '补充已留在草稿中。此演示没有实时模型，请导入包含这条补充的新响应后查看差异。' : '先写下想调整什么。')}>保留补充</button></details>
    </>}
    {activeStep === 2 && plan && <>
      <section className="generation-section"><h2>从结果推导可观测指标</h2><p className="meta">不是每条 KR 都是一个数字；数值结果绑定指标，交付结果保留验收条目。</p>{plan.metrics.map(m => <article className="generated-metric" key={m.id}><small>{plan.keyResults.find(kr => kr.id === m.krId)?.title}</small><h3>{m.name}</h3><p>{m.rationale}</p><small>{m.formula.op === 'field' ? `读取原始字段 ${m.formula.field}` : m.formula.op === 'difference' ? `${m.formula.field} 减有效周期起点` : `${m.formula.numerator} / ${m.formula.denominator}，同一账号、日期与口径`}</small></article>)}</section>
      <section className="generation-section"><h2>据此组合看板</h2><div className="widget-mapping">{plan.widgets.map(w => <div key={w.id}><FileTextIcon size={18} /><span>{w.title}<small>{({ metric:'指标卡',trend:'日期趋势',records:'数据明细',checks:'验收清单' })[w.type]} · {w.metricIds.map(id => plan.metrics.find(m => m.id === id)?.name).join('、') || plan.keyResults.find(kr => kr.id === w.krId)?.title}</small></span><ChevronRight size={16} /></div>)}</div></section>
      <button type="button" className="button primary" onClick={() => onStep(3)}>确认衡量方案，寻找数据</button>
    </>}
    {activeStep === 3 && plan && <>
      <section className="generation-section"><h2>为选定指标形成连接方案</h2><p>智能体查找可用能力，定位数据，再把读取与校验方式保存成可重复执行的连接。</p><p className="meta">当前回放提供候选描述，尚未访问真实第三方后台。连接器的代码与回执放在详情里。</p></section>
      {plan.connectors.map(c => <section className="generation-section" key={c.id}><div className="section-head"><h3>{c.name}</h3><span className="meta">浏览器 / v{c.revision}</span></div><ol className="connector-steps"><li>定位已授权的后台，检查登录态。</li><li>核对账号 {c.expectedAccountId} 和观测日期。</li><li>提取 {c.fields.map(f => f.id).join('、')}，核对单位与缺失。</li><li>输出带来源、时间、版本的样本；校验后才绑定。</li></ol><p className="meta">缺登录时请你在原浏览器完成；页面变化时保留旧数据并重新定位、复验。</p><details><summary><TerminalIcon size={16} /> 可执行连接描述与代码</summary><p className="meta">通用 runner 读取这份 JSON；模型可生成新描述，服务先验证再执行。这里不运行模型生成的任意脚本。</p><pre className="generation-code">{JSON.stringify(c,null,2)}</pre><div className="choice-row"><button type="button" className="button" onClick={() => download(`${c.id}.json`,c)}>下载连接描述</button><a href="browser-metric-connector.mjs">查看浏览器 runner</a></div><pre className="generation-code">{`node browser-metric-connector.mjs --spec ${c.id}.json --target <浏览器标签 ID> --out sample.json`}</pre><p className="meta">内容增长样例配有本地后台夹具；项目监控地址是占位，未实现真实接入。</p></details></section>)}
      <button type="button" className="button primary" onClick={() => onStep(4)}>验证读取结果</button>
    </>}
    {activeStep === 4 && plan && <>
      <section className="generation-section"><h2>把连接方案变成已核对的数据来源</h2><p>需要账号、日期、原始字段与读取回执。一个网址或一段生成代码不代表连接成功。</p><label className="field">回放情形<select value={scenario} onChange={e => { setScenario(e.target.value);setError('');setStatus('') }}><option value="ready">取得样本</option><option value="login">需要登录</option><option value="missing">字段发生变化</option><option value="account">账号不符</option></select></label><button type="button" className="button" onClick={() => {
        if (scenario === 'login') { setStatus('需要登录：请在授权的后台浏览器完成，再重新读取；目前没有新数据。');return }
        const row = replayObservation(plan)
        if (scenario === 'missing') delete row.values[Object.keys(row.values)[0]]
        if (scenario === 'account') row.accountId = 'another-account'
        acceptSample(row)
      }}>回放一次浏览器读取</button><label className="field generation-import">或导入实际 runner 的 sample.json<input type="file" accept="application/json,.json" onChange={e => readFile(e,value => { try { acceptSample(JSON.parse(value)) } catch { setError('不是有效 JSON，请重新导入。') } })} /></label><p className="meta">实际 runner 可在本地夹具执行；导入这里只校验协议、账号、字段和日期，文件本身不构成第三方平台认证。</p></section>
      {records.length > 0 && <section className="generation-section"><h3>已核对样本</h3>{records.map(r => <div className="sample-receipt" key={`${r.connectorId}:${r.date}`}><CheckIcon size={18} /><span>{r.date} / {r.accountId}<small>{r.evidenceKind === 'replay' ? '响应回放数据' : '本地夹具 · 浏览器实际读取'} · {Object.entries(r.values).map(([id,v]) => `${id} ${v.value}${v.unit}`).join('；')}</small></span></div>)}<label className="check-row"><input type="checkbox" checked={baseline} onChange={e => setBaseline(e.target.checked)} /><span>用周期前一日的有效快照建立净增起点<small>周期从 {plan.cycleStart} 开始；缺少 {previousDay(plan.cycleStart)} 的数据时仍保持未知。</small></span></label></section>}
      <button type="button" className="button primary" onClick={() => onStep(5)}>{records.length ? '生成看板，保留未接入项' : '先生成待接入看板'}</button>
    </>}
    {activeStep === 5 && effective && <>
      <section className="generation-section"><h2>{effective.objective}</h2><p className="meta">{effective.keyResults.length} 条 KR · {effective.metrics.length} 个指标 · {effective.widgets.length} 个组件 · 修订 {effective.revision}</p><label className="field">观测日期<input type="date" value={date} onChange={e => e.target.value && setDate(e.target.value)} /></label><p className="meta">{sourceRecords.length ? sourceRecords.every(r => r.evidenceKind === 'browser-fixture') ? '当前日期：本地夹具实际读取' : '当前日期包含回放示例' : '该日无数据，保留为空。'}</p></section>
      <div className="generated-board">{effective.widgets.map(w => {
        const metrics = w.metricIds.map(id => effective.metrics.find(m => m.id === id)!)
        return <section className={`generated-widget widget-${w.type}`} key={w.id} data-widget-type={w.type}><h3>{w.title}</h3>
          {w.type === 'metric' && metrics.map(m => {
            const value = measuredValue(m,records,date), before = measuredValue(m,records,previousDay(date))
            return <div key={m.id}><span className="generated-value">{shown(value,m.unit)}</span><p className="meta">{m.name} · 较前日 {value === null || before === null ? '待比较' : `${value - before > 0 ? '+' : ''}${Number((value-before).toFixed(2))}${m.unit === '%' ? ' 个百分点' : m.unit}`}</p>{degraded.includes(m.connectorId) && <p className="warn-text">来源待修复；这里保留原日期数据。</p>}</div>
          })}
          {w.type === 'trend' && metrics.map(m => <DateTrend key={m.id} metric={m} records={records} />)}
          {w.type === 'checks' && <ul className="generated-items">{effective.keyResults.find(kr => kr.id === w.krId)?.items?.map(item => <li key={item}>{item}<small>待产物证据核验</small></li>)}</ul>}
          {w.type === 'records' && <div className="history-table"><table><thead><tr><th>日期</th>{metrics.map(m => <th key={m.id}>{m.name}</th>)}<th>证据</th></tr></thead><tbody>{[...new Set(records.map(r => r.date))].sort().map(at => <tr key={at}><td><button type="button" className="date-link" onClick={() => setDate(at)}>{at}</button></td>{metrics.map(m => <td key={m.id}>{shown(measuredValue(m,records,at),m.unit)}</td>)}<td>{records.filter(r => r.date === at).map(r => <small key={r.connectorId}>{r.accountId} / v{r.connectorRevision} / {r.evidenceKind === 'replay' ? '回放' : '浏览器夹具'}</small>)}</td></tr>)}</tbody></table>{!records.length && <p className="meta">尚无有效记录。</p>}</div>}
        </section>
      })}</div>
      <section className="generation-section"><h3>每天沿同一份约定运行</h3><p>{effective.dailyAction}</p><p className="meta">读取、核对、按日期追加、计算变化，再提出行动建议。计划完成不代替结果达成；来源失效不补数。</p><div className="choice-row"><button type="button" className="button" disabled={degraded.length > 0} onClick={() => acceptSample(replayObservation(effective,'2026-11-12'))}>回放次日填数</button><button type="button" className="button" onClick={() => { setDegraded(effective.connectors.map(c => c.id));setStatus('页面字段变化：连接已停用，旧记录保留。需要重新定位、生成修订并通过取样后恢复。') }}>回放来源失效</button><button type="button" className="button" onClick={() => onStep(4)}>返回来源复验</button><button type="button" className="button" onClick={() => onStep(1)}>调整目标与 KR</button></div><p><a href="#/cycle">继续体验 project 与每日复盘闭环（独立示例）</a></p></section>
    </>}
    {status && <p className="generation-status" role="status">{status}</p>}
    {error && <p className="error-text generation-status" role="alert">{error}</p>}
    <details className="generation-section"><summary>导入生成方案 / 查看响应协议</summary><p className="meta">此处用于验证同一渲染器处理任意合法响应；不会执行其中的代码。更换方案会清空本轮样本，既有整体面板不受影响。</p><label className="field">方案 JSON<textarea rows={8} value={response} onChange={e => setResponse(e.target.value)} placeholder="粘贴 schemaVersion: 1 的 GeneratedPlan" /></label><div className="choice-row"><button type="button" className="button" onClick={() => setResponse(JSON.stringify(plan ?? replayOptions[replayIndex].plan,null,2))}>载入当前响应</button><button type="button" className="button" onClick={importPlan}>应用响应</button><button type="button" className="button" onClick={() => download('measurement-plan.json',plan ?? replayOptions[replayIndex].plan)}>导出方案</button></div><p><a href="technical-design.html#dynamic-connector">阅读动态连接机理</a></p></details>
    <div className="form-actions">{activeStep > 0 && <button type="button" className="button" onClick={() => onStep(activeStep-1)}>上一步</button>}<a href="#/panel">查看已有整体面板</a></div>
  </div>
}
