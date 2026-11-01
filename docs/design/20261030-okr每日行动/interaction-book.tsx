import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { useLayout } from '../../../frontend/src/layout'
import { CheckIcon, ChevronLeft, ChevronRight, FolderIcon, PlayIcon, TerminalIcon } from '../../../frontend/src/icons'
import SwarmRuntime from './okr-swarm-runtime'
import { CycleKind, cycleActions, cycleDefinitions, dailyDelta, latestCycleReview } from './okr-execution-cycle'
import { BrowserObservation, formulaFields } from './okr-generation-contract'
import { DateTrend, KrProposal } from './okr-generation'
import { DialogueScene, dialogueScenes, sceneAt, sceneSnapshot, sceneOffsets, scenePlan, storyDuration, storylines, sceneLifecycle } from './okr-dialogue-scenes'

const designNotes: Record<DialogueScene['view'],{ input: string; processing: string; output: string; boundary: string }> = {
  launch:{input:'用户采用搭建方案并启动长期 Swarm。',processing:'固化生效配置、目标关联、成员职责、任务依赖与触发策略。',output:'从搭建对话切换为 Swarm 运行工作台，持续展示成员、任务、数据与复盘。',boundary:'长期保存的是组织和工作状态；成员可按事件唤醒。此处仅回放，不创建真实蜂群。'},
  intent:{input:'用户提出尚不完整的方向，再说明周期、结果期待和投入。',processing:'主责澄清成功标准，区分用户明确要求、建议和未知事实。',output:'O 草稿、已知约束和待确认项；此时尚未展示 KR 或结果数据。',boundary:'先聊目标，不要求用户先填 KR 表，也不提前读取后台或假定实际基线。'},
  goals:{input:'用户口述方向，随后补充时间、约束和验收要求。',processing:'模型提出 O、长短 KR、假设和少量必要问题；新回答生成方案修订。',output:'KR 按数值、阶段、清单等含义呈现，数量和内容随方案变化。',boundary:'建议目标须可辨认；实际基线不能猜。用户修改方向后相关方案需重新核对。'},
  metrics:{input:'用户确认结果方向，请求整理衡量方式。',processing:'从 KR 推导结果、派生和诊断指标，分析公式依赖、窗口与原始字段。',output:'指标理由、候选看板组件和待接入状态。',boundary:'指标确认之前不执行来源发现；诊断好转不直接计入长期 KR。'},
  source:{input:'用户告知数据所在后台或请智能体寻找访问方式。',processing:'发现实际能力，定位账号与字段，形成 connector，取样后校验。',output:'需要登录、候选连接、样本回执、已绑定与待接入项分别呈现。',boundary:'生成代码不等于接通。页面、账号、日期或字段不符时保留旧值并复验。此设计书不访问真实后台。'},
  board:{input:'用户采用衡量方案与已核对样本，要求生成并保存整体看板。',processing:'组件引用确认的 KR 和指标，建立日期记录、来源与更新约定。',output:'看板起点、日期趋势、验收区、缺失状态和事件更新规则。',boundary:'生成看板不等于数据完整；未采集日期不补造，任务事件不替代业务结果。'},
  handoff:{input:'主责派发任务，或数据职能提交新观测。',processing:'职责按任务和证据接棒；交付事件与观测事件分别更新对应投影。',output:'当前接棒者、任务/数据状态、回填记录与实际更新时间。',boundary:'已有交付可先登板，业务结果仍等数据。实时呈现已有事件，不代表实时生成未知数据。'},
  decision:{input:'人查看当前数据和解释，决定继续、调整或暂停。',processing:'把选择关联当前 Review 与计划；暂停后续执行时保留已发生的事实。',output:'可操作的继续/暂停、明确的状态与后续计划。',boundary:'演示控制只改变本地回放；不能将暂停按钮说成已停止真实运行任务。'},
  projects:{input:'用户指定已有项目、素材位置与可投入时间。',processing:'解析稳定 project 身份和执行范围，把行动关联到项目。',output:'一个目标关联多个项目；主责、执行、取数、复盘按任务分工。',boundary:'不为每条 KR 建仓库。没有项目也可先观察；绑定目录不等于获得外部账号或发布权限。'},
  work:{input:'用户采用近期实验与每日工作约定。',processing:'主责依据上次复盘形成任务，在具体项目内执行并核验产物。',output:'脚本、候选视频、PR、测试结果以及明确的发布状态。',boundary:'能力不足准确停在草稿或阻塞；候选交付不代表已发布，也不代表线上达标。'},
  review:{input:'到达回顾窗口，或用户询问当天表现。',processing:'数据角色提交日期事实，复盘角色读取冻结证据并区分事实与假设。',output:'日增量、周期结果、成熟度、解释和继续/调整/补测建议。',boundary:'缺数据不补零。没有随机分流的内容比较标为探索性，不宣布因果胜出。'},
  next:{input:'用户采用建议，或系统在既有约定内例行推进。',processing:'主责把有效 Review 转成下一天计划，记录来源和输入版本。',output:'可执行的新行动、负责项目、验收要求与计划修订。',boundary:'晚到数据使旧复盘失效；已执行任务不被覆写，不重复派发已交付内容。'},
}
const formatTime = (ms: number) => `${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`
const Workspace = React.memo(function Workspace({ kind, scene, flowPaused, onContinue, onPause }: { kind: CycleKind; scene: DialogueScene; flowPaused?: boolean; onContinue?: () => void; onPause?: () => void }) {
  const plan = scenePlan(kind,scene.revision), definition = cycleDefinitions[kind], state = sceneSnapshot(kind,scene)
  const review = latestCycleReview(state), latest = state.observations.at(-1)!
  const current = state.observations.find(row => row.date === state.activeDate), delivered = state.delivered[state.activeDate] ?? []
  const net = kind === 'creator' ? latest.value-definition.baseline : latest.value
  const responsibilities = [
    ['主责',flowPaused ? '暂停后续派发' : scene.checkpoint === 'next' ? '已生成次日计划' : '维护当前计划与接力'],
    ['执行',flowPaused ? '不启动新动作，已有产物保留' : delivered.length ? '交付已核验并回填' : '待执行，按项目验收'],
    ['数据',current ? '观测已校验并回填' : '等待采集窗口或来源恢复'],
    ['复盘',review ? '已形成依据与建议' : current ? '接棒，待独立分析' : '等待交付与观测证据'],
  ]
  const boardStats = <div className="book-board-stats"><article><small>{kind === 'creator' ? '周期净增 / 长期目标' : '发布版 p95 / 长期目标'}</small><strong>{net} / {definition.target}{definition.unit}</strong></article><article><small>{latest.date} 最新有效观测</small><strong>{latest.value}{definition.unit}</strong><small>{current ? `较前日 ${dailyDelta(state,state.activeDate)! > 0 ? '+' : ''}${dailyDelta(state,state.activeDate)}${definition.unit}` : `${state.activeDate} 尚无新观测`}</small></article></div>
  const metric = plan.metrics.find(m => m.formula.op === 'field')!
  const records: BrowserObservation[] = state.observations.map(row => ({ connectorId:metric.connectorId,connectorRevision:1,accountId:kind === 'creator' ? 'demo-creator' : 'pocketboard-demo',date:row.date,capturedAt:`${row.date}T13:00:00Z`,sourceUrl:'https://example.invalid/replay',evidenceKind:'replay',values:Object.fromEntries(formulaFields(metric).map(field => [field,{value:row.value,unit:metric.unit}])) }))
  return <>
    <header className="book-output-head"><span className="eyebrow">生成结果 / {scene.title}</span><h2>{plan.objective}</h2><p className="meta">{scene.view === 'intent' ? scene.intentConfirmed ? '目标约定' : 'O 草稿' : `方案 r${scene.revision}`}</p></header>
    {scene.view === 'intent' && <>
      <section className="book-section"><p className="eyebrow">{scene.intentConfirmed ? '已聊清的目标约定' : '先聊方向'}</p><p>{scene.intentConfirmed ? definition.longResult : kind === 'creator' ? '希望持续分享 AI 编程内容，成功标准还需要确认。' : '希望完成基本功能并持续维护，使用场景与结果还需要确认。'}</p></section>
      <section className="book-section"><h3>{scene.intentConfirmed ? '已知约束' : '需要聊清什么'}</h3><ul className="book-facts">{(scene.intentConfirmed ? ['八周周期',kind === 'creator' ? '每天参与半小时' : '每天留一小时评审','实际基线与可用数据来源待核对'] : ['主要追求什么结果','希望推进多久','每天能投入多少、哪些安排要保留']).map(item => <li key={item}>{item}</li>)}</ul><p className="meta">{scene.intentConfirmed ? '下一步由智能体提出 KR 和衡量方式。' : '尚未拆分 KR，也没有生成结果面板。'}</p></section>
    </>}
    {scene.view === 'goals' && <>
      {kind === 'creator' && scene.revision === 2 && <p className="book-change" role="status">方案已调整：KR 从 2 条变 3 条，增加互动诊断和短期验收要求。</p>}
      <div className="generated-krs">{plan.keyResults.map((kr,index) => <KrProposal key={kr.id} kr={kr} index={index} />)}</div>
      <section className="book-section"><h3>近期先验证什么</h3><p>{definition.shortResult}</p><small>长期结果与短期检查点分开衡量，实际起点待读取。</small></section>
    </>}
    {scene.view === 'metrics' && <>
      <div className="book-metric-list">{plan.metrics.map(m => <article key={m.id}><span className="book-status">待接入</span><h3>{m.name}</h3><p>{m.rationale}</p><small>原始字段：{formulaFields(m).join('、')}</small></article>)}</div>
      <section className="book-section"><h3>看板随指标组成</h3><div className="book-widget-map">{plan.widgets.map(w => <span key={w.id}>{w.title}<small>{({metric:'指标卡',trend:'日期趋势',records:'明细',checks:'验收清单'})[w.type]}</small></span>)}</div></section>
    </>}
    {scene.view === 'source' && <>
      <section className="book-section"><div className="section-head"><h3>{kind === 'creator' ? '创作者后台 / 浏览器读取' : '发布监控 / 浏览器或报告读取'}</h3><span className={scene.sampled ? 'ok-text' : 'warn-text'}>{scene.sampled ? '回放样本已核对' : '候选连接 · 待验证'}</span></div><ol className="connector-steps"><li>发现可用能力与后台入口。</li><li>核对登录、稳定账号或项目身份。</li><li>读取观测日期、字段、单位和版本。</li><li>保存回执，验证通过后登记连接。</li></ol></section>
      {scene.sampled ? <div className="book-receipt"><CheckIcon size={20} /><div><h3>{kind === 'creator' ? 'demo-creator / 2026-11-11' : 'demo-v0.4 / 固定负载'}</h3><strong>{kind === 'creator' ? '粉丝 328 人' : '发布版 p95 720ms'}</strong><small>{kind === 'creator' ? '周期从 11 月 12 日开始；可用作净增起点。单视频同龄结果另行核对。' : '候选环境独立记录，不覆盖这条发布事实。'}</small></div></div> : <p className="book-change">需要登录或没有访问能力时，停在待接入，不能把未知数据填成 0。</p>}
      <details className="book-section"><summary><TerminalIcon size={16} /> 连接描述与设计边界</summary><pre className="generation-code">{JSON.stringify(plan.connectors[0],null,2)}</pre><p className="meta">这是回放中的连接描述。本地夹具 runner 的可执行验证和真实平台接入边界见技术文档。</p><a href="technical-design.html#dynamic-connector">查看 connector 机理</a></details>
    </>}
    {scene.view === 'board' && <>
      <p className="book-change">整体看板已生成并保存（回放） · {scene.id === 'schedule' ? '更新约定已设定' : '等待设置更新约定'}</p>{boardStats}
      <section className="book-section"><h3>日期趋势</h3><DateTrend metric={metric} records={records} /><small>目前只有已核对的起点样本，其他日期等待有效观测。</small></section>
      <section className="book-section"><h3>关键区域和状态</h3><div className="book-widget-map">{plan.widgets.map(w => <span key={w.id}>{w.title}<small>{w.type === 'checks' ? '等待产物与验收事件' : w.metricIds.includes(metric.id) ? '起点已核对，持续积累日期数据' : '等待所需字段或有效观测'}</small></span>)}</div></section>
      <section className="book-section"><h3>更新约定</h3><ul className="book-facts"><li>任务验收事件更新交付区，保留产物与时间。</li><li>账号/发布数据按约定取数，观测到达后更新结果和趋势。</li><li>单视频按观察龄采集；来源失效保留旧值并提示处理。</li></ul></section>
    </>}
    {scene.view === 'projects' && <>
      {definition.projects.map(project => <section className="book-project" key={project.id}><FolderIcon size={22} /><div><h3>{project.name}</h3><p>{project.contribution}</p><small>{project.directory}（示例） · {project.git ? 'Git 项目，任务使用独立 worktree' : '素材目录项目'}</small></div><span className="ok-text">回放关联</span></section>)}
      <section className="book-section"><h3>一个主责，按任务协作</h3><div className="book-role-grid">{[['主责','维护目标与跨天计划'],['执行','在项目内交付产物'],['数据','取数并提交事实'],['复盘','独立分析证据']].map(([role,duty]) => <div key={role}><b>{role}</b><small>{duty}</small></div>)}</div><p className="meta">职责不是四个常驻会话。任务可独立并行时才增加执行者。</p></section>
    </>}
    {['handoff','work','review','decision','next'].includes(scene.view) && <section className="book-section" aria-label="职能分工与当前接力"><h3>职能分工与当前接力</h3><div className="book-role-grid">{responsibilities.map(([role,status]) => <div key={role}><b>{role}</b><small>{status}</small></div>)}</div><p className="meta">同一个主责维护目标，其他职能按任务运行；各自提交证据后接棒。</p></section>}
    {['handoff','work'].includes(scene.view) && <>
      {boardStats}<section className="book-section"><h3>当前回填记录</h3>{state.events.length ? state.events.map((event,index) => <p className="meta" key={index}>{event}</p>) : <p>主责已形成任务安排，执行与数据职能等待各自的开始条件。</p>}<p className="book-decision">{current ? '观测事件已更新业务结果；复盘等待或读取这份证据。' : delivered.length ? '任务事件已更新交付区；当前日期的业务结果仍待采集。' : '尚未执行，不显示交付完成或新的业务结果。'}</p></section>
    </>}
    {scene.view === 'work' && <>
      <section className="book-section"><p className="eyebrow">短周期假设</p><h3>{definition.experiment}</h3></section>{cycleActions(state,kind).map(action => <section className="book-section" key={action.id}><span className="book-status">执行角色 / {definition.projects.find(p => p.id === action.projectId)?.name}</span><h3>{action.title}</h3><p>{action.artifact}</p><small>验收：{action.acceptance}</small><details><summary>产物内容示例</summary><pre className="generation-code">{action.preview}</pre></details></section>)}
    </>}
    {['review','decision','next'].includes(scene.view) && review && <>
      {boardStats}
      {scene.view !== 'next' && <section className="book-section"><h3>{kind === 'creator' ? '粉丝按日期变化' : '发布环境趋势'}</h3><DateTrend metric={metric} records={records} /></section>}
      <section className="book-section"><h3>事实与判断</h3><ul className="book-facts">{review.facts.map(fact => <li key={fact}>{fact}</li>)}</ul><p className="book-decision">{review.decision}</p></section>
      {scene.view === 'review' && <details className="book-section"><summary>原始观测与可能的解释</summary>{state.variantObservations.map(row => <p className="meta" key={`${row.videoId}:${row.ageHours}`}>{row.videoId} · {row.ageHours}h · 完整 {row.completed} / 有效 {row.plays} · {row.source}</p>)}{review.hypotheses.map(h => <p key={h}>{h}</p>)}</details>}
      {scene.view === 'decision' && <section className="book-section"><h3>根据当前证据做决定</h3><p>可以继续验证，也可以暂停后续自动执行。目标、看板和已发生的事实保留。</p>{onContinue && onPause ? <div className="choice-row"><button type="button" className="button primary" disabled={flowPaused} onClick={onContinue}>{kind === 'creator' ? '继续单变量验证' : '继续评审与验证'}</button><button type="button" className="button" disabled={flowPaused} onClick={onPause}>暂停后续执行</button></div> : <ul className="book-facts"><li>继续验证：形成关联本次 Review 的新计划。</li><li>暂停：不再启动新动作，历史和已交付内容保留。</li></ul>}{flowPaused && <p className="warn-text">后续执行已暂停（回放）；可继续查看数据，恢复后从当前决定继续。</p>}</section>}
      <section className="book-section"><p className="eyebrow">{scene.view === 'next' ? `进入下一轮的计划 / ${state.plans.at(-1)?.date}` : '下一步行动'}</p><h3>{review.nextAction}</h3><small>关联原始 Review 和输入版本；长期 KR 不被这段建议改写。</small></section>
    </>}
  </>
})
function DesignNote({ scene }: { scene: DialogueScene }) {
  const notes = designNotes[scene.view]
  return <div className="book-design-note"><p className="eyebrow">交互设计说明 / {scene.title}</p>{([['输入',notes.input],['系统处理',notes.processing],['界面输出',notes.output],['状态边界',notes.boundary]] as const).map(([name,value]) => <section className="book-section" key={name}><h3>{name}</h3><p>{value}</p></section>)}<p><a href="technical-design.html">阅读完整技术设计</a></p></div>
}
type PendingTurn = { text: string; after: number }
const previousSceneIds = {creator:['result','goal','revise','metrics','discover','sample','projects','work','first-review','second-review','next'],repo:['result','goal','metrics','discover','sample','projects','work','first-review','next']}
function restoreDialogue(kind: CycleKind) {
  try {
    const saved = JSON.parse(localStorage.getItem(`roami-okr-design-book:${kind}`) ?? 'null')
    if (saved && Number.isInteger(saved.index) && typeof saved.started === 'boolean' && typeof saved.draft === 'string' && Array.isArray(saved.pending)) {
      const oldId = saved.sceneId ?? previousSceneIds[kind][saved.index]
      const index = Math.max(0,dialogueScenes[kind].findIndex(scene => scene.id === oldId))
      const pending = saved.pending.filter((turn:PendingTurn) => typeof turn.text === 'string' && Number.isInteger(turn.after)).map((turn:PendingTurn) => ({...turn,after:saved.sceneId ? turn.after : Math.max(0,dialogueScenes[kind].findIndex(scene => scene.id === previousSceneIds[kind][turn.after]))}))
      return {index,started:saved.started,draft:saved.draft,pending,flowPaused:saved.flowPaused === true}
    }
  } catch {}
  return { index:0,started:false,draft:dialogueScenes[kind][0].user,pending:[] as PendingTurn[],flowPaused:false }
}
function Book({ kind, setKind }: { kind: CycleKind; setKind: (kind: CycleKind) => void }) {
  const layout = useLayout(), scenes = dialogueScenes[kind], offsets = sceneOffsets(kind), total = storyDuration(kind)
  const [saved] = useState(() => restoreDialogue(kind))
  const [mode,setMode] = useState<'story'|'interactive'>(() => new URLSearchParams(location.search).get('mode') === 'interactive' ? 'interactive' : 'story')
  const [elapsed,setElapsed] = useState(() => offsets[Math.max(0,Math.min(scenes.length-1,Math.trunc(Number(new URLSearchParams(location.search).get('scene')) || 0)))])
  const [playing,setPlaying] = useState(false), [speed,setSpeed] = useState(1)
  const [index,setIndex] = useState(saved.index), [started,setStarted] = useState(saved.started)
  const [draft,setDraft] = useState(saved.draft), [pending,setPending] = useState<PendingTurn[]>(saved.pending)
  const [flowPaused,setFlowPaused] = useState(saved.flowPaused)
  const [pane,setPane] = useState<'chat'|'output'|'notes'>(() => new URLSearchParams(location.search).get('mode') === 'interactive' ? 'chat' : 'output')
  const conversation = useRef<HTMLDivElement>(null), output = useRef<HTMLDivElement>(null)
  const active = mode === 'story' ? sceneAt(kind,elapsed) : index, scene = scenes[active]
  const visible = mode === 'story' || started
  const isRuntime = visible && sceneLifecycle(scene) === 'running'
  const nextIndex = Math.min(scenes.length-1,index+1)
  const turnIndices = visible ? Array.from({length:active+1},(_,i) => i) : []
  const chapters = storylines.map(line => line.title)
  useEffect(() => { if (isRuntime) setPane('output') },[isRuntime])
  useEffect(() => { try { localStorage.setItem(`roami-okr-design-book:${kind}`,JSON.stringify({index,sceneId:scenes[index].id,started,draft,pending,flowPaused})) } catch {} },[kind,index,started,draft,pending,flowPaused])
  useEffect(() => {
    if (!playing || mode !== 'story') return
    let frame = 0, last = performance.now(), carry = 0
    const tick = (now: number) => { carry += Math.min(now-last,100)*speed;last = now;if (carry >= 100) { const delta = carry;carry = 0;setElapsed(old => Math.min(total,old+delta)) };frame = requestAnimationFrame(tick) }
    frame = requestAnimationFrame(tick)
    const visibility = () => { if (document.hidden) setPlaying(false) }
    document.addEventListener('visibilitychange',visibility)
    return () => { cancelAnimationFrame(frame);document.removeEventListener('visibilitychange',visibility) }
  },[playing,mode,speed,total])
  useEffect(() => { if (elapsed >= total) setPlaying(false) },[elapsed,total])
  useEffect(() => { if (conversation.current) conversation.current.scrollTop = conversation.current.scrollHeight;if (output.current) output.current.scrollTop = 0 },[active,mode,started,pending.length])
  useEffect(() => {
    const keydown = (e: KeyboardEvent) => {
      if (mode !== 'story' || (e.target instanceof HTMLElement && ['INPUT','TEXTAREA','SELECT','BUTTON','A'].includes(e.target.tagName))) return
      if (e.code === 'Space') { e.preventDefault();setElapsed(old => old >= total ? 0 : old);setPlaying(p => !p) }
      if (e.key === 'ArrowRight') { e.preventDefault();setElapsed(offsets[Math.min(scenes.length-1,active+1)]) }
      if (e.key === 'ArrowLeft') { e.preventDefault();setElapsed(offsets[Math.max(0,active-1)]) }
    }
    addEventListener('keydown',keydown);return () => removeEventListener('keydown',keydown)
  },[mode,active,kind])
  function changeMode(value: 'story'|'interactive') { const url = new URL(location.href);url.searchParams.set('mode',value);history.replaceState(null,'',url);setPlaying(false);setMode(value);setPane(value === 'interactive' ? 'chat' : 'output') }
  function send(value = draft) {
    if (!value.trim() || flowPaused) return
    const destination = started ? nextIndex : 0
    if (value.trim() !== scenes[destination].user.trim() || started && index === scenes.length-1) { setPending(p => [...p,{text:value,after:index}]);setDraft('');setPane('chat');return }
    setIndex(destination);setStarted(true);setDraft(destination+1 < scenes.length ? scenes[destination+1].user : '');setPane('output')
  }
  function jump(i: number) { setElapsed(offsets[i]);setPlaying(false);setPane('output') }
  return <div className="interaction-book">
    <header className="book-topbar tt-pagehead"><div><h1>从目标到每天的行动</h1><p className="desktop-only">OKR 交互设计书 · 用户输入、智能体响应与生成结果</p></div><a href="index.html">产品设计</a></header>
    <div className="book-toolbar"><label>场景<select aria-label="选择故事" value={kind} onChange={e => setKind(e.target.value as CycleKind)}><option value="creator">AI 编程短视频</option><option value="repo">持续维护 repo</option></select></label><div className="book-mode" aria-label="设计书体验方式"><button type="button" aria-pressed={mode === 'story'} onClick={() => changeMode('story')}>看故事</button><button type="button" aria-pressed={mode === 'interactive'} onClick={() => changeMode('interactive')}>自己推进</button></div><span className="book-replay-label">{isRuntime ? '运行态 · 长期 Swarm 工作台 · 回放' : '搭建态 · KR 与看板生成 · 回放'}</span></div>
    <nav className="book-chapters book-storylines" aria-label="四条故事线的顺序">{chapters.map(chapter => <button type="button" className={chapter === scene.chapter ? 'active' : ''} key={chapter} aria-current={chapter === scene.chapter ? 'step' : undefined} onClick={() => {if (mode === 'interactive') changeMode('story');jump(scenes.findIndex(s => s.chapter === chapter))}}>{chapter}</button>)}</nav>
    {mode === 'interactive' && flowPaused && <div className="book-pause-state" role="status"><span>后续执行已暂停（回放），目标和看板保留。</span><button type="button" className="button" onClick={() => setFlowPaused(false)}>恢复推进</button></div>}
    <nav className="book-mobile-tabs" aria-label="查看对话或结果">{([['chat','对话'],['output','生成结果'],['notes','设计说明']] as const).map(([value,label]) => <button type="button" key={value} className={pane === value ? 'active' : ''} aria-pressed={pane === value} onClick={() => {setPane(value);if (value !== 'output') setPlaying(false)}}>{isRuntime && value === 'chat' ? '与主责对话' : isRuntime && value === 'output' ? 'Swarm 工作台' : label}</button>)}</nav>
    <main className="book-stage" data-pane={pane} data-state={isRuntime ? 'running' : 'building'}>
      <section className="book-chat" aria-label="用户输入与智能体响应"><header className="book-panehead"><h2>{isRuntime ? '和主责对话' : '和 Roami 对话'}</h2><small>{mode === 'story' ? '沿着故事，看一段输入如何改变工作台' : '发送示例输入，或保留自己的补充'}</small></header><div className="book-chat-scroll" ref={conversation} aria-live={mode === 'interactive' ? 'polite' : 'off'}>
        {!visible && <article className="book-turn assistant"><small>Roami</small><p>说说你想持续推进的目标。我会先整理结果，再分析衡量方式和行动。</p></article>}
        {turnIndices.map(i => <React.Fragment key={scenes[i].id}><article className="book-turn user"><small>你 / {scenes[i].title}</small><p>{scenes[i].user}</p></article><article className={`book-turn assistant ${i === active ? 'current' : ''}`}><small>Roami</small><p>{scenes[i].reply}</p>{mode === 'interactive' && i === active && i < scenes.length-1 && <button type="button" className="button primary" disabled={flowPaused} onClick={() => send(scenes[i+1].user)}>{scenes[i].action ?? '继续这个故事'}<ChevronRight size={16} /></button>}</article>{mode === 'interactive' && pending.filter(turn => turn.after === i).map((turn,n) => <React.Fragment key={n}><article className="book-turn user"><small>你的补充</small><p>{turn.text}</p></article><article className="book-turn assistant"><small>离线设计演示</small><p>输入已保留。当前没有对应的实时模型响应，右侧保持原方案；可继续示例或在完整原型中导入方案。</p></article></React.Fragment>)}</React.Fragment>)}
        {!started && mode === 'interactive' && pending.filter(turn => turn.after === index).map((turn,n) => <article className="book-turn user" key={n}><small>你的输入已保留</small><p>{turn.text}</p><small>离线设计书尚无对应模型响应，尚未生成方案。</small></article>)}
      </div>{mode === 'interactive' && <div className="book-composer"><label htmlFor="book-input">输入或补充目标</label><textarea id="book-input" rows={3} value={draft} onChange={e => setDraft(e.target.value)} /><div className="book-composer-actions"><button type="button" className="tt-act" onClick={() => setDraft(scenes[started ? nextIndex : 0].user)}>填入示例</button><button type="button" className="button primary" disabled={!draft.trim() || flowPaused} onClick={() => send()}>发送</button></div></div>}</section>
      <section className="book-output" aria-label={isRuntime ? 'Swarm 长期运行工作台' : '随输入变化的工作台'} ref={output}>
        {layout.phone && visible && !isRuntime && <details className="book-current-input" key={scene.id}><summary>本幕输入与响应</summary><small>你的输入</small><p>{scene.user}</p><small>智能体响应</small><p>{scene.reply}</p></details>}
        {isRuntime ? <SwarmRuntime kind={kind} scene={scene} paused={mode === 'interactive' && flowPaused} onPause={mode === 'interactive' ? () => setFlowPaused(true) : undefined} onResume={() => setFlowPaused(false)} onContinue={mode === 'interactive' && index < scenes.length-1 ? () => send(scenes[nextIndex].user) : undefined} onChat={() => {setPane('chat');setPlaying(false)}} /> : visible ? <Workspace kind={kind} scene={scene} flowPaused={mode === 'interactive' && flowPaused} onContinue={mode === 'interactive' ? () => send(scenes[nextIndex].user) : undefined} onPause={mode === 'interactive' ? () => setFlowPaused(true) : undefined} /> : <div className="book-empty"><h2>工作台从你的描述开始</h2><p>发送目标后，KR、指标、连接方式和每日计划会在这里逐步出现。</p></div>}
        {visible && <details className="book-section book-desktop-notes"><summary>本幕交互设计说明</summary><DesignNote scene={scene} /></details>}
      </section><section className="book-notes-pane" aria-label="本幕设计说明"><DesignNote scene={scene} /></section>
    </main>
    {mode === 'story' ? <footer className="book-player"><p className="book-caption" aria-live="off">{scene.caption}</p><div className="book-playback"><button type="button" className="button" onClick={() => { if (elapsed >= total) setElapsed(0);setPlaying(p => !p);setPane('output') }}>{!playing && <PlayIcon size={16} />}{playing ? '暂停' : elapsed >= total ? '重播' : '播放演示'}</button><button type="button" className="icon-button" aria-label="上一幕" onClick={() => jump(Math.max(0,active-1))}><ChevronLeft size={20} /></button><button type="button" className="icon-button" aria-label="下一幕" onClick={() => jump(Math.min(scenes.length-1,active+1))}><ChevronRight size={20} /></button><input className="book-seek" type="range" min={0} max={total} value={Math.min(elapsed,total)} aria-label="故事进度" onChange={e => {setElapsed(Number(e.target.value));setPlaying(false)}} /><span className="book-time">{formatTime(elapsed)} / {formatTime(total)}</span><select aria-label="播放速度" value={speed} onChange={e => setSpeed(Number(e.target.value))}><option value={1}>1 倍</option><option value={1.5}>1.5 倍</option><option value={2}>2 倍</option></select></div></footer> : <footer className="book-interactive-foot"><span>{visible ? `${active+1} / ${scenes.length} · ${scene.title}` : '从一句目标开始'}</span><button type="button" className="tt-act" onClick={() => {setIndex(0);setStarted(false);setDraft(scenes[0].user);setPending([]);setFlowPaused(false);setPane('chat')}}>重新体验</button><a href={`prototype.html#/cycle/${kind}`}>完整闭环原型</a></footer>}
  </div>
}
function App() {
  const [kind,setKind] = useState<CycleKind>(() => new URLSearchParams(location.search).get('case') === 'repo' ? 'repo' : 'creator')
  return <Book key={kind} kind={kind} setKind={value => { const url = new URL(location.href);url.searchParams.set('case',value);url.searchParams.delete('scene');history.replaceState(null,'',url);setKind(value) }} />
}
createRoot(document.getElementById('root')!).render(<App />)
