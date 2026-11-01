import React, { useEffect, useRef, useState } from 'react'
import { CheckIcon, ChevronRight, FolderIcon } from '../../../frontend/src/icons'
import { activeCyclePlan, applyNextPlan, collectCycleData, cycleActions, cycleDefinitions, CycleKind, CycleState, dailyDelta, deliverAction, initialCycle, latestCycleReview, matureComparison, reviewCycle, reviewIsCurrent } from './okr-execution-cycle'

const STORE = 'roami-okr-cycle-v1'
const tabs = ['目标与项目','今日行动','取数与复盘','明日计划']
const roles = [
  ['主责智能体','记住长期 KR 和上次复盘，形成短周期实验，分配今天的任务。','按规划、事件和复盘唤醒，无需一直占用会话。'],
  ['执行角色','在关联 project 内制作候选视频或实现代码，提交产物并按验收条件复核。','任务级运行；可并行时才扩展多个执行者。'],
  ['数据角色','复用 connector 读取已授权来源，校验日期、账号和口径，追加事实。','有独立读写范围；不以执行者的描述代替数据。'],
  ['复盘角色','读取冻结的交付证据和观测，区分事实、假设与建议。','独立复盘任务；不直接修改原始数或擅改长期目标。'],
]
function restore(kind: CycleKind): CycleState {
  try {
    const saved = JSON.parse(localStorage.getItem(`${STORE}:${kind}`) ?? 'null')
    if (saved && Array.isArray(saved.plans) && Array.isArray(saved.observations) && ['2026-11-12','2026-11-13'].includes(saved.activeDate)) return { ...saved,variantObservations:saved.variantObservations ?? [],candidateResults:saved.candidateResults ?? [] }
  } catch {}
  return initialCycle(kind)
}
const changeText = (value: number|null,unit: string) => value === null ? '待比较' : `${value > 0 ? '+' : ''}${value}${unit}`
export default function OkrCycle({ kind }: { kind: CycleKind }) {
  const [state,setState] = useState(() => restore(kind))
  const [tab,setTab] = useState(0)
  const [horizon,setHorizon] = useState('continuous')
  const [selectedDate,setSelectedDate] = useState(state.activeDate)
  const [dataScenario,setDataScenario] = useState('ready')
  const [notice,setNotice] = useState('')
  const [error,setError] = useState('')
  const root = useRef<HTMLDivElement>(null)
  const definition = cycleDefinitions[kind], plan = activeCyclePlan(state), actions = cycleActions(state,kind)
  const current = state.observations.find(row => row.date === selectedDate)
  const comparison = matureComparison(state,selectedDate)
  const review = latestCycleReview(state), currentReview = reviewIsCurrent(state)
  const nextDate = state.activeDate === '2026-11-12' ? '2026-11-13' : '2026-11-14'
  const nextPlan = state.plans.findLast(plan => plan.date === nextDate)
  const nextAdopted = !!nextPlan && nextPlan.sourceReviewKey === review?.inputKey && currentReview
  useEffect(() => { try { localStorage.setItem(`${STORE}:${kind}`,JSON.stringify(state)) } catch {} },[state,kind])
  useEffect(() => { setNotice('');setError('');requestAnimationFrame(() => root.current?.scrollIntoView({ block:'start' })) },[tab])
  const act = (operation: () => CycleState, message: string) => {
    try { setState(operation());setError('');setNotice(message) } catch(e) { setError(e instanceof Error ? e.message : '未完成，请检查当前状态。') }
  }
  function switchDay() {
    if (!nextAdopted || state.activeDate !== '2026-11-12') return
    setState({ ...state,activeDate:nextDate });setSelectedDate(nextDate);setDataScenario('ready');setTab(1)
  }
  return <div className="cycle-page" ref={root}>
    <div className="tt-pagehead"><div><p className="eyebrow">目标、执行、观测与学习</p><h1 className="desktop-only">每日实验闭环</h1><p>长期目标保持方向，每天用新证据调整行动。</p></div></div>
    <p className="generation-mode">闭环回放 · 未创建真实目录、任务或发布</p>
    <div className="cycle-toolbar"><label>示例<select aria-label="闭环示例" value={kind} onChange={e => { location.hash = `/cycle/${e.target.value}` }}><option value="creator">短视频创作</option><option value="repo">Repo 维护</option></select></label><span>工作日 {state.activeDate}</span><button type="button" className="tt-act" onClick={() => { setState(initialCycle(kind));setSelectedDate('2026-11-12');setTab(0);setNotice('已恢复本闭环示例。');setError('') }}>重置回放</button></div>
    <nav className="cycle-tabs" aria-label="每日闭环视图">{tabs.map((label,index) => <button type="button" key={label} aria-pressed={tab === index} className={tab === index ? 'active' : ''} onClick={() => setTab(index)}>{label}</button>)}</nav>
    {notice && <p className="cycle-feedback" role="status">{notice}</p>}{error && <p className="cycle-feedback error-text" role="alert">{error}</p>}
    {tab === 0 && <>
      <section className="cycle-section"><p className="eyebrow">大目标 O</p><h2>{definition.objective}</h2><div className="cycle-horizons"><article><small>长期 KR · 2026-11-12 至 2027-01-06</small><h3>{definition.longResult}</h3><p className="meta">表达长期结果；不会因一次交付完成或短期波动而自动改目标。</p></article><article><small>短期 KR / 检查点 · 11 月 12–18 日</small><h3>{definition.shortResult}</h3><p className="meta">关联长期 KR，使用明确的窗口、假设和判断条件。</p></article></div><p>{definition.experiment}</p></section>
      <section className="cycle-section"><div className="section-head"><h2>同一个目标，两种观察方式</h2></div><div className="choice-row"><button type="button" className={`button ${horizon === 'continuous' ? 'selected' : ''}`} aria-pressed={horizon === 'continuous'} onClick={() => setHorizon('continuous')}>持续追踪</button><button type="button" className={`button ${horizon === 'daily' ? 'selected' : ''}`} aria-pressed={horizon === 'daily'} onClick={() => setHorizon('daily')}>按日看增量</button></div><label className="field">观测日期<select value={selectedDate} onChange={e => setSelectedDate(e.target.value)}>{[...new Set([...state.observations.map(row => row.date),state.activeDate])].sort().map(date => <option key={date}>{date}</option>)}</select></label>
        {horizon === 'continuous' ? <div className="cycle-readout"><div><small>{kind === 'creator' ? '长期 KR 的已观测净增' : '发布版已观测性能'}</small><strong>{current ? kind === 'creator' ? `${current.value-definition.baseline} / ${definition.target}人` : `${current.value}ms / 目标不高于 ${definition.target}ms` : '等待观测'}</strong></div><div><small>短周期实验状态</small><strong>{kind === 'creator' ? comparison ? '同龄样本可比较，结论仍待验证' : '等待发布后 24h 数据' : '候选与发布版分别核验'}</strong></div></div> : <div className="cycle-readout"><div><small>{definition.metricName}</small><strong>{current ? `${current.value}${definition.unit}` : '待更新'}</strong></div><div><small>较前一日</small><strong>{changeText(dailyDelta(state,selectedDate),definition.unit)}</strong></div></div>}
        <p className="meta">每天看变化，每周看短周期结果；不把八周目标平均摊成每日硬指标，也不把任务完成率当 KR 达成率。</p>
      </section>
      <section className="cycle-section"><h2>让 project 承载执行</h2><p>目标可以先建。需要执行时关联已有项目；一条目标可以由多个 project 支持，同一 project 也可服务多个目标。</p>{definition.projects.map(project => <label className="cycle-project" key={project.id}><input type="checkbox" checked={state.linkedProjects.includes(project.id)} onChange={e => { const linkedProjects = e.target.checked ? [...state.linkedProjects,project.id] : state.linkedProjects.filter(id => id !== project.id);setState({ ...state,linkedProjects });setError('') }} /><FolderIcon size={20} /><span><b>{project.name}</b><small>{project.contribution}</small><small>{project.git ? 'Git 项目' : '素材目录项目'} · {project.directory}（示例）</small></span></label>)}<p className="meta">project 是有稳定身份和执行资源的项目；目录是它的工作根。Git 改动使用独立 worktree，浏览器数据来源不等于项目目录。</p></section>
      <section className="cycle-section"><h2>一个主责，按任务组织角色</h2><p>主责智能体负责目标的连续性；执行、取数、复盘按需启动独立任务，不要求每个 project 常驻一群智能体。</p><div className="cycle-roles">{roles.map(([name,duty,lifecycle]) => <article key={name}><h3>{name}</h3><p>{duty}</p><small>{lifecycle}</small></article>)}</div></section>
      <div className="form-actions"><button type="button" className="button primary" onClick={() => setTab(1)}>查看今天怎么执行</button></div>
    </>}
    {tab === 1 && <>
      <section className="cycle-section"><p className="eyebrow">主责智能体的今日计划 · r{plan?.revision}</p><h2>{plan?.focus}</h2><p className="meta">{plan?.sourceReviewKey ? '来自上一次复盘的已采用建议；可追溯原始数据和判断。' : '首次计划基于短周期假设；完成后回收实际反馈。'}</p><p>关联：{definition.longResult}；近期：{definition.shortResult}。</p></section>
      {actions.map(action => {
        const delivered = (state.delivered[state.activeDate] ?? []).includes(action.id), project = definition.projects.find(p => p.id === action.projectId)!
        return <article className="cycle-action" key={action.id}><div className="section-head"><h3>{action.title}</h3><span className={delivered ? 'ok-text meta' : 'meta'}>{delivered ? '回放验收通过' : '待执行'}</span></div><small>执行角色 / {project.name} / {project.git ? '独立 worktree' : '按日素材目录'}</small><p>{action.artifact}</p><p className="meta">验收：{action.acceptance}。</p>{!state.linkedProjects.includes(project.id) && <p className="warn-text">尚未关联这个 project，无法派发这项行动。</p>}<div className="choice-row"><button type="button" className="button" disabled={delivered} onClick={() => act(() => deliverAction(state,kind,action.id),'本项交付与验收已回放；结果指标尚未因此改变。')}>回放执行与验收</button><button type="button" className="button" onClick={() => setTab(0)}>查看项目关联</button></div><details><summary>交付内容示例</summary><pre className="generation-code">{action.preview}</pre></details></article>
      })}
      {!actions.length && <p className="cycle-section">本轮优先补齐观测，不重复生产候选。</p>}
      <section className="cycle-section"><h3>一天如何推进</h3><ol className="connector-steps"><li>规划：主责读取上次回顾和未完成任务，选择今天的实验与行动。</li><li>执行：在关联 project 准备视频或代码，返回产物与验收证据。</li><li>取数：数据角色通过 connector 读取实际来源并按日期写入。</li><li>复盘：独立任务分析事实与假设，主责据此形成下一天计划。</li></ol><p className="meta">真实产品按约定时段和任务事件自动流转；本页用回放按钮展示每个状态。</p></section><button type="button" className="button primary" onClick={() => setTab(2)}>进入取数与复盘</button>
    </>}
    {tab === 2 && <>
      <section className="cycle-section"><p className="eyebrow">21:00 / 数据角色</p><h2>先写事实，再做判断</h2><label className="field">数据到达情形<select aria-label="数据到达情形" value={dataScenario} onChange={e => setDataScenario(e.target.value)}><option value="ready">数据可读取</option><option value="late">平台数据延迟</option><option value="login">后台需要重新登录</option></select></label><button type="button" className="button" onClick={() => {
        if (dataScenario !== 'ready') { setNotice(dataScenario === 'late' ? '平台数据尚未就绪；保留旧日期，今日未知。' : '需要在原后台重新登录；未写入新数据。');setError('');return }
        act(() => collectCycleData(state,kind),'样例观测已按日期写入；同日重试不会重复累计。');setSelectedDate(state.activeDate)
      }}>回放采集并填入看板</button><div className="history-table cycle-history"><table><thead><tr><th>日期</th><th>{definition.metricName}</th><th>较前一日</th><th>来源</th></tr></thead><tbody>{state.observations.map(row => <tr key={row.date}><td>{row.date}</td><td>{row.value}{definition.unit}</td><td>{changeText(dailyDelta(state,row.date),definition.unit)}</td><td><small>{row.source}<br />{row.dataReadyAt}</small></td></tr>)}</tbody></table></div>{kind === 'creator' && state.variantObservations.length > 0 && <details><summary>视频实验的原始观测与观察龄</summary><div className="history-table"><table><thead><tr><th>视频</th><th>观察龄</th><th>完整 / 有效播放</th><th>来源</th></tr></thead><tbody>{state.variantObservations.map(row => <tr key={`${row.videoId}:${row.ageHours}`}><td>{row.videoId}</td><td>{row.ageHours}h</td><td>{row.completed} / {row.plays}</td><td>{row.source}</td></tr>)}</tbody></table></div></details>}<p className="meta">交付与观测分开。{kind === 'creator' ? '没有视频归因数据，不把账号涨粉归到某条视频。' : '候选 PR 的 280ms 不覆盖发布版 720ms。'}</p></section>
      <section className="cycle-section"><p className="eyebrow">21:10 / 复盘角色</p><h2>根据证据形成今日复盘</h2><p>独立读取本轮交付和观测快照；数据不足时先指出缺项，不编造效果。</p><button type="button" className="button primary" onClick={() => act(() => reviewCycle(state,kind),'今日复盘已按当前证据生成（回放）。')}>回放独立复盘</button>
        {review && <div className="cycle-review"><p className={currentReview ? 'ok-text meta' : 'warn-text'}>{currentReview ? '复盘对应当前证据' : '数据或交付已变化，请更新复盘'}</p><h3>事实</h3><ul>{review.facts.map(fact => <li key={fact}>{fact}</li>)}</ul><h3>可能的解释</h3><ul>{review.hypotheses.map(hypothesis => <li key={hypothesis}>{hypothesis}</li>)}</ul><h3>下一步判断</h3><p>{review.decision}</p></div>}
      </section><div className="form-actions"><button type="button" className="button" onClick={() => setTab(0)}>回到长期与每日面板</button><button type="button" className="button primary" onClick={() => setTab(3)}>查看明日调整</button></div>
    </>}
    {tab === 3 && <>
      <section className="cycle-section"><p className="eyebrow">主责智能体 / 计划修订</p><h2>把学习落实为 {nextDate} 的行动</h2>{review ? <><p>{review.nextAction}</p><p className="meta">{review.waiting ? '这轮数据未齐，下一天优先测量；不宣布实验成功。' : '只调整下一轮行动，不改写长期 KR、历史数据或既有交付。'}</p>{!currentReview && <p className="warn-text">证据已更新，先重新复盘再采用。</p>}<button type="button" className="button primary" disabled={nextAdopted} onClick={() => act(() => applyNextPlan(state),'建议已进入次日计划，保留复盘来源和计划修订。')}>{nextAdopted ? '已纳入次日计划' : '回放纳入次日计划'}</button></> : <p>先完成一次基于证据的复盘。</p>}{nextPlan && <div className="cycle-plan-receipt"><CheckIcon size={18} /><span>{nextPlan.date} / 计划 r{nextPlan.revision}<small>{nextPlan.focus}</small><small>{nextPlan.mode === 'measurement' ? '优先测量，不重复生产' : '继续执行与验证'} · 长期 KR 保持</small></span></div>}</section>
      <section className="cycle-section"><h3>继续第二天，查看反馈如何回来</h3><p>{kind === 'creator' ? '第二天样例粉丝从 334 降到 332，面板保留下跌；满 24 小时的样片才能进入同龄对比。' : '候选 PR 完成后，发布版仍需等待合并、发布和独立复验。'}</p>{state.activeDate === '2026-11-12' ? <button type="button" className="button" disabled={!nextAdopted} onClick={switchDay}>进入 11 月 13 日计划<ChevronRight size={16} /></button> : <p className="meta">第二轮也可形成后续计划；本演示只回放两个工作日。</p>}</section>
      <details className="cycle-section"><summary>查看本轮流转记录</summary>{state.events.length ? state.events.map((event,index) => <p className="meta" key={index}>{event}</p>) : <p className="meta">尚未开始回放。</p>}</details>
    </>}
    <p className="cycle-doc-link"><a href="index.html#okr-project-loop">阅读目标、project 与智能体的关系</a> · <a href="technical-design.html#cycle-runtime">查看运行时契约</a></p>
  </div>
}
