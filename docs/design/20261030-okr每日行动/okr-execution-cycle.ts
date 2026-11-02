export type CycleKind = 'creator' | 'repo'
export type CycleProject = { id: string; name: string; directory: string; git: boolean; contribution: string }
export type CycleAction = { id: string; projectId: string; title: string; artifact: string; acceptance: string; preview: string }
export type CycleDefinition = {
  kind: CycleKind; objective: string; longResult: string; shortResult: string; experiment: string;
  metricName: string; unit: string; target: number; baseline: number; direction: 'up' | 'down';
  projects: CycleProject[]; actions: CycleAction[];
}
export type CycleObservation = { date: string; value: number; revision: number; source: string; dataReadyAt: string; plays?: number; completed?: number; watchSeconds?: number }
export type VariantObservation = { videoId: string; variant: 'A'|'B'; ageHours: number; plays: number; completed: number; watchSeconds?: number; durationSeconds?: number; collectedDate: string; source: string }
export type CandidateResult = { date: string; actionId: string; commit: string; p95: number; environment: string }
export type CycleReview = { date: string; inputKey: string; facts: string[]; hypotheses: string[]; decision: string; nextAction: string; waiting: boolean }
export type CycleDayPlan = { date: string; revision: number; sourceReviewKey: string|null; focus: string; mode: 'production'|'measurement' }
export type CycleState = {
  linkedProjects: string[]; delivered: Record<string,string[]>; observations: CycleObservation[]; variantObservations: VariantObservation[]; candidateResults: CandidateResult[];
  reviews: CycleReview[]; activeDate: string; plans: CycleDayPlan[]; events: string[];
}
export const cycleDefinitions: Record<CycleKind,CycleDefinition> = {
  creator:{
    kind:'creator',objective:'让 AI 编程短视频持续获得真实关注',longResult:'八周净增 200 个真实粉丝',shortResult:'本周验证更短开场；同为约 45 秒视频，T+24h 完播率参考目标 30%、平均观看 18 秒',experiment:'保持主题和时长相近，只调整开场；无法随机分流，按探索性内容对比记录。',
    metricName:'粉丝总量',unit:'人',target:200,baseline:328,direction:'up',
    projects:[
      { id:'content-studio',name:'AI 编程栏目',directory:'/workspace/ai-content',git:false,contribution:'选题、脚本、视频与发布记录' },
      { id:'content-tools',name:'内容自动化工具',directory:'/workspace/content-tools',git:true,contribution:'维护渲染脚本与数据 connector' },
    ],
    actions:[
      { id:'video-draft',projectId:'content-studio',title:'制作 5 秒开场的候选视频',artifact:'video-v2.mp4 + script-v2.md',acceptance:'演示可复现、字幕与步骤一致，发布沿用既有授权',preview:'00:00 展示完成后的公众号草稿\n00:05 演示 AI 编程生成步骤\n00:35 给出复现入口\n候选文件需要任务产物与验收记录；本页仅回放。' },
      { id:'capture-contract',projectId:'content-tools',title:'核对视频 ID 与发布后 24 小时取数口径',artifact:'connector revision + sample receipt',acceptance:'账号、视频 ID、发布时间、观察龄与分母一致',preview:'variant_id / video_id / published_at\nobservation_age_hours = 24\nplays / completed / watch_seconds / likes\n没有视频归因字段时，账号涨粉不能归因到某条视频。' },
    ],
  },
  repo:{
    kind:'repo',objective:'让 PocketBoard 可用且持续响应快',longResult:'八周内发布版 API p95 降至 300ms 以下',shortResult:'本周固定负载下验证一项索引优化，并完成候选回归',experiment:'固定数据集、并发和基准环境；候选版本和线上发布版本分开。',
    metricName:'发布版 API p95',unit:'ms',target:300,baseline:720,direction:'down',
    projects:[{ id:'pocketboard',name:'PocketBoard',directory:'/workspace/pocketboard',git:true,contribution:'实现、测试、候选 PR 与发布后复验' }],
    actions:[{ id:'index-candidate',projectId:'pocketboard',title:'定位查询瓶颈，提交索引优化候选 PR',artifact:'候选 PR + benchmark report',acceptance:'固定负载复测、核心流程回归；发布后另行复验',preview:'候选 PR demo-index：p95 280ms\n发布版 demo-v0.4：p95 720ms\n候选通过不代表已合并、已发布或线上达标。' }],
  },
}
export function initialCycle(kind: CycleKind): CycleState {
  const definition = cycleDefinitions[kind]
  return { linkedProjects:[],delivered:{},observations:[{ date:'2026-11-11',value:definition.baseline,revision:1,source:kind === 'creator' ? '示例账号 creator-01 / 粉丝快照' : '示例发布版 demo-v0.4 / 固定负载',dataReadyAt:'2026-11-11 21:00',...(kind === 'creator' ? {plays:600,completed:144,watchSeconds:8400} : {}) }],variantObservations:[],candidateResults:[],reviews:[],activeDate:'2026-11-12',plans:[{ date:'2026-11-12',revision:1,sourceReviewKey:null,focus:definition.actions[0].title,mode:'production' }],events:[] }
}
export function activeCyclePlan(state: CycleState): CycleDayPlan|undefined { return state.plans.findLast(plan => plan.date === state.activeDate) }
export function cycleActions(state: CycleState, kind: CycleKind): CycleAction[] {
  const plan = activeCyclePlan(state)
  if (!plan || plan.mode === 'measurement') return []
  return cycleDefinitions[kind].actions.map((action,index) => index === 0 ? { ...action,title:plan.focus } : action)
}
export function dailyDelta(state: CycleState, date: string): number|null {
  const previous = new Date(Date.parse(`${date}T12:00:00Z`) - 86400000).toISOString().slice(0,10)
  const current = state.observations.find(row => row.date === date), before = state.observations.find(row => row.date === previous)
  return current && before ? current.value - before.value : null
}
export function deliverAction(state: CycleState, kind: CycleKind, actionId: string): CycleState {
  const action = cycleActions(state,kind).find(action => action.id === actionId)
  if (!action || !state.linkedProjects.includes(action.projectId)) throw new Error('先关联这项行动使用的 project。')
  const ids = state.delivered[state.activeDate] ?? []
  if (ids.includes(actionId)) return state
  return { ...state,delivered:{ ...state.delivered,[state.activeDate]:[...ids,actionId] },candidateResults:kind === 'repo' ? [...state.candidateResults,{ date:state.activeDate,actionId,commit:'demo-index',p95:280,environment:'candidate / fixed-load' }] : state.candidateResults,events:[...state.events,`${state.activeDate} · ${action.title} · 回放交付与验收`] }
}
export function collectCycleData(state: CycleState, kind: CycleKind): CycleState {
  const accountExists = state.observations.some(row => row.date === state.activeDate)
  const value = kind === 'creator' ? state.activeDate === '2026-11-12' ? 334 : 332 : 720
  const incoming: VariantObservation[] = kind === 'creator' ? [
    {videoId:'video-a',variant:'A',ageHours:24,plays:1000,completed:240,watchSeconds:14000,durationSeconds:45,collectedDate:state.activeDate,source:'示例视频 A / T+24h 历史快照回放'},
    {videoId:'video-b',variant:'B',ageHours:state.activeDate === '2026-11-12' ? 3 : 24,plays:state.activeDate === '2026-11-12' ? 300 : 1000,completed:state.activeDate === '2026-11-12' ? 90 : 320,watchSeconds:state.activeDate === '2026-11-12' ? 4800 : 19000,durationSeconds:45,collectedDate:state.activeDate,source:'示例视频 B / 观察龄与原始数回放'},
  ] : []
  const newVariants = incoming.filter(row => !state.variantObservations.some(old => old.videoId === row.videoId && old.ageHours === row.ageHours))
  if (accountExists && !newVariants.length) return state
  return { ...state,observations:accountExists ? state.observations : [...state.observations,{ date:state.activeDate,value,revision:1,source:kind === 'creator' ? '示例 creator-01 / 浏览器 connector 回放' : '示例发布版 demo-v0.4 / 监控回放',dataReadyAt:`${state.activeDate} 21:00`,...(kind === 'creator' ? state.activeDate === '2026-11-12' ? {plays:700,completed:224,watchSeconds:12600} : {plays:600,completed:162,watchSeconds:10200} : {}) }],variantObservations:[...state.variantObservations,...newVariants],events:[...state.events,`${state.activeDate} · 数据角色核对账号、日期、观察龄与字段后写入（回放）`] }
}
export function matureComparison(state: CycleState, date: string) {
  const control = state.variantObservations.findLast(row => row.variant === 'A' && row.ageHours === 24 && row.collectedDate <= date)
  const treatment = state.variantObservations.findLast(row => row.variant === 'B' && row.ageHours === 24 && row.collectedDate <= date)
  if (!control || !treatment || control.plays <= 0 || treatment.plays <= 0) return null
  const a = control.completed/control.plays*100, b = treatment.completed/treatment.plays*100
  return { control,treatment,a,b,change:b-a,averageA:control.watchSeconds === undefined ? null : control.watchSeconds/control.plays,averageB:treatment.watchSeconds === undefined ? null : treatment.watchSeconds/treatment.plays }
}
export function reviewInputKey(state: CycleState): string {
  return JSON.stringify({ date:state.activeDate,observations:state.observations.filter(row => row.date <= state.activeDate).map(row => [row.date,row.value,row.revision,row.plays,row.completed,row.watchSeconds]),variants:state.variantObservations.filter(row => row.collectedDate <= state.activeDate),candidates:state.candidateResults.filter(row => row.date === state.activeDate),delivered:state.delivered[state.activeDate] ?? [] })
}
export function latestCycleReview(state: CycleState): CycleReview|undefined {
  return state.reviews.findLast(review => review.date === state.activeDate)
}
export function reviewIsCurrent(state: CycleState): boolean { return latestCycleReview(state)?.inputKey === reviewInputKey(state) }
export function reviewCycle(state: CycleState, kind: CycleKind): CycleState {
  if (reviewIsCurrent(state)) return state
  const definition = cycleDefinitions[kind], row = state.observations.find(row => row.date === state.activeDate), delta = dailyDelta(state,state.activeDate)
  const actions = cycleActions(state,kind), delivered = actions.filter(action => (state.delivered[state.activeDate] ?? []).includes(action.id))
  const facts = [actions.length ? `今日 ${delivered.length}/${actions.length} 项行动有回放验收记录。` : '今日计划优先补齐观测，没有新的生产任务。']
  const hypotheses: string[] = []
  let nextAction: string, decision: string
  if (!row || delta === null) {
    facts.push('当日或前一日数据未齐，今日增量未知；未补零。')
    hypotheses.push('数据缺失可能来自延迟或登录失效，需由采集任务核实。')
    decision = '先补齐观测，不判断实验效果。'; nextAction = '恢复取数并核对观察窗口，保留原实验条件。'
  } else if (kind === 'creator') {
    facts.push(`账号粉丝 ${row.value} 人；较前日 ${delta > 0 ? '+' : ''}${delta} 人；周期净增 ${row.value-definition.baseline} 人。`)
    const quality = watchQuality(row)
    facts.push(`账号当日完播率 ${quality.completion === null ? '未知' : quality.completion+'%'}（参考目标 30%）；平均观看 ${quality.average === null ? '未知' : quality.average+' 秒'}（参考目标 18 秒），与粉丝 KR 分别衡量。`)
    const comparison = matureComparison(state,state.activeDate)
    if (!comparison) {
      const young = state.variantObservations.findLast(row => row.variant === 'B' && row.collectedDate <= state.activeDate)
      facts.push(young ? `新视频发布仅 ${young.ageHours} 小时，发布后 24 小时对比尚未成熟。` : '缺少可比较的发布后 24 小时视频快照。')
      decision = '继续观察，不因当日涨粉就判定开场有效。'; nextAction = '保留主题与风格，采集同一观察龄的数据，再准备下一条单变量样片。'
    } else {
      facts.push(`两条历史样片的 T+24h 快照：A ${comparison.control.completed}/${comparison.control.plays}=${comparison.a}%，B ${comparison.treatment.completed}/${comparison.treatment.plays}=${comparison.b}%；差 ${comparison.change} 个百分点。`)
      facts.push(`T+24h 平均观看：A ${comparison.averageA === null ? '未知' : comparison.averageA+' 秒'}，B ${comparison.averageB === null ? '未知' : comparison.averageB+' 秒'}；视频片长分别为 ${comparison.control.durationSeconds ?? '未知'} / ${comparison.treatment.durationSeconds ?? '未知'} 秒。`)
      decision = '样例 B 完播率达到参考线；平均观看另行核对，不能据此宣布整体 KR 达标。没有随机分流，仍需多轮验证。'; nextAction = '结合账号完播率与平均观看的差距，保持主题与片长，继续验证短开场；下一条只改变一个因素。'
    }
    hypotheses.push('短开场可能改善观看，但发布时间、受众和推荐流量也可能造成差异；账号净增没有单视频归因。')
  } else {
    facts.push(`发布版 p95 ${row.value}ms；较前日 ${delta}ms；目标不高于 ${definition.target}ms。`)
    const candidate = state.candidateResults.findLast(result => result.date === state.activeDate)
    if (candidate) facts.push(`候选 PR ${candidate.commit} 的固定负载结果为 ${candidate.p95}ms；当前发布版仍为 ${row.value}ms。`)
    hypotheses.push('候选优化可能有效，需在合并和获授权发布后以同口径复验。')
    decision = '候选交付与线上结果分开，不提前更新长期 KR。'; nextAction = '完成候选评审和回归；具备发布授权后发布，并独立复验发布版。'
  }
  if (actions.length && !delivered.length) hypotheses.push('没有已核验的今日交付，不能声称计划已经执行。')
  const review: CycleReview = { date:state.activeDate,inputKey:reviewInputKey(state),facts,hypotheses,decision,nextAction,waiting:!row || delta === null }
  return { ...state,reviews:[...state.reviews,review],events:[...state.events,`${state.activeDate} · 复盘角色基于观测水位生成回顾 r${state.reviews.filter(r => r.date === state.activeDate).length+1}（回放）`] }
}
export function applyNextPlan(state: CycleState): CycleState {
  if (!reviewIsCurrent(state)) throw new Error('数据或交付有变化，请先更新复盘。')
  const nextDate = new Date(Date.parse(`${state.activeDate}T12:00:00Z`) + 86400000).toISOString().slice(0,10)
  const review = latestCycleReview(state)!, existing = state.plans.findLast(plan => plan.date === nextDate)
  if (existing?.sourceReviewKey === review.inputKey) return state
  if (state.delivered[nextDate]?.length) throw new Error('次日已有任务交付，保留原任务；需要另建增量调整。')
  const plan: CycleDayPlan = { date:nextDate,revision:(existing?.revision ?? 0)+1,sourceReviewKey:review.inputKey,focus:review.nextAction,mode:review.waiting ? 'measurement' : 'production' }
  return { ...state,plans:[...state.plans,plan],events:[...state.events,`${state.activeDate} · 主智能体将复盘建议纳入 ${nextDate} 计划 r${plan.revision}（回放）`] }
}

export function watchQuality(row?: Pick<CycleObservation,'plays'|'completed'|'watchSeconds'>) {
  const plays = row?.plays
  return { completion:plays && row?.completed !== undefined ? row.completed/plays*100 : null,average:plays && row?.watchSeconds !== undefined ? row.watchSeconds/plays : null }
}
