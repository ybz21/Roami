import type { SetupDraft } from './okr-setup-model'
export type Metric = { id: string; name: string; unit: string; baseline: number; target: number; direction: 'up' | 'down'; channel: string; window: string; source: string; decimals?: number; krId?: string; role?: string; rationale?: string; baselineKnown?: boolean; baselineDate?: string; targetKnown?: boolean; bindingState?: 'bound' | 'pending' }
export type Snapshot = { date: string; followers?: number; likes?: number; plays?: number; completed?: number; journeys?: number; p95?: number; retained?: number; source: string; author: string; received: string; reason?: string }
export type Goal = { setup?: SetupDraft; sourceHistory?: { setup:SetupDraft; observations:Record<string,Snapshot> }[]; board?: { showTrend: boolean }; id: string; kind: 'creator' | 'repo'; title: string; short: string; objective: string; start: string; end: string; minutes: number; metrics: Metric[]; observations: Record<string, Snapshot>; revisions: Snapshot[]; phase: number; adopted: boolean; paused: boolean; daily: boolean; statement: string }
export const TODAY = '2026-11-12'
export const STORE = 'roami-okr-prototype-v3'
export const creatorMetrics: Metric[] = [
  { id: 'followers', name: '粉丝数', unit: '人', baseline: 300, target: 500, direction: 'up', channel: '视频号', window: '当日总量', source: '视频号后台关注快照' },
  { id: 'likes', name: '点赞量', unit: '次', baseline: 80, target: 300, direction: 'up', channel: '视频号', window: '近 7 日', source: '视频号每日数据导出' },
  { id: 'rate', name: '点赞率', unit: '%', baseline: 3, target: 5, direction: 'up', channel: '视频号', window: '近 7 日', source: '点赞量 / 有效播放量', decimals: 2 },
  { id: 'completion', name: '完播率', unit: '%', baseline: 25, target: 40, direction: 'up', channel: '视频号', window: '近 7 日', source: '完整播放量 / 有效播放量', decimals: 2 },
]
export const repoMetrics: Metric[] = [
  { id: 'journeys', name: '核心旅程', unit: '条', baseline: 0, target: 4, direction: 'up', channel: '发布版本', window: '当前版本', source: '发布版本端到端复验' },
  { id: 'p95', name: 'API p95', unit: 'ms', baseline: 900, target: 300, direction: 'down', channel: '固定基准', window: '当前版本', source: '1 万条任务 / 20 并发基准' },
  { id: 'retained', name: '连续四周使用', unit: '人', baseline: 0, target: 4, direction: 'up', channel: '试用组', window: '本周期', source: '五位入组用户的有效使用记录' },
]
export const creatorStatement = '我想用八周持续讲解如何利用 AI 编程做公众号和视频号。视频号粉丝从 300 到 500，近七天点赞量达到 300、点赞率达到 5%、完播率达到 40%。每天帮我准备内容，晚上整理数据，我每天能投入半小时。'
export const repoStatement = '我想把 PocketBoard 从基础功能做成持续可用的项目。八周内发布版四条核心旅程通过，API p95 从 900ms 降到 300ms，五个试用者中四个人连续使用四周。每天推进，保留一小时给我评审。'
const raw = [
  [302, 12, 400, 100], [305, 15, 500, 125], [308, 15, 600, 144], [310, 15, 600, 144],
  [311, 10, 414, 140], [312, 15, 550, 130], [315, 25, 650, 150], [320, 20, 600, 140],
  [324, 25, 650, 160], [322, 15, 500, 120], [328, 10, 636, 160], [334, 40, 700, 340],
]
export function fixture(kind: Goal['kind'], date = TODAY): Snapshot {
  const index = Math.max(0, Math.min(11, Number(date.slice(-2)) - 1))
  if (kind === 'repo') return { date, journeys: 4, p95: [900, 900, 880, 860, 820, 790, 810, 780, 760, 740, 720, 720][index], retained: 0, source: '发布版 demo-v0.4 · 固定基准与有效使用记录（示例）', author: '每日智能体', received: `${date} 21:00` }
  const [followers, likes, plays, completed] = raw[index]
  return { date, followers, likes, plays, completed, source: '视频号粉丝快照 / 当日数据导出（示例）', author: '每日智能体', received: `${date} 21:00` }
}
export function initialGoals(): Goal[] {
  const observations = (kind: Goal['kind']) => Object.fromEntries(Array.from({ length: 11 }, (_, i) => { const date = `2026-11-${String(i + 1).padStart(2, '0')}`; return [date, fixture(kind, date)] }))
  return [
    { id: 'creator', kind: 'creator', title: '让 AI 编程内容被更多人看懂并持续关注', short: '内容增长', objective: '八周内，把 AI 编程做公众号和视频号的分享，做成有人看完、愿意点赞并持续关注的栏目。', start: '2026-11-02', end: '2026-12-27', minutes: 30, metrics: creatorMetrics, observations: observations('creator'), revisions: [], phase: 0, adopted: false, paused: false, daily: true, statement: creatorStatement },
    { id: 'repo', kind: 'repo', title: '让 PocketBoard 可日常使用、响应快且持续可维护', short: 'PocketBoard', objective: '八周内，从基本功能走到发布验收、性能优化和持续维护。', start: '2026-11-02', end: '2026-12-27', minutes: 60, metrics: repoMetrics, observations: observations('repo'), revisions: [], phase: 0, adopted: false, paused: false, daily: true, statement: repoStatement },
  ]
}
export function previous(date: string, amount = 1) { const value = new Date(`${date}T12:00:00Z`); value.setUTCDate(value.getUTCDate() - amount); return value.toISOString().slice(0, 10) }
export function valueAt(goal: Goal, metric: Metric, date: string): number | null {
  if (metric.bindingState === 'pending') return null
  const snapshot = goal.observations[date]
  if (!snapshot) return null
  if (metric.id === 'netFollowers') { const source = goal.metrics.find(m => m.id === 'followers'); return snapshot.followers !== undefined && source && source.baselineKnown !== false ? snapshot.followers - source.baseline : null }
  if (goal.kind === 'repo' || metric.id === 'followers') return (snapshot as unknown as Record<string, number>)[metric.id] ?? null
  const days = Array.from({ length: 7 }, (_, i) => goal.observations[previous(date, i)]).filter(Boolean)
  if (days.length !== 7) return null
  const needed = metric.id === 'likes' ? ['likes'] : metric.id === 'rate' ? ['likes','plays'] : ['completed','plays']
  if (days.some(row => needed.some(key => (row as unknown as Record<string, unknown>)[key] === undefined))) return null
  const sum = (key: 'likes' | 'plays' | 'completed') => days.reduce((count, row) => count + (row[key] ?? 0), 0)
  if (metric.id === 'likes') return sum('likes')
  const plays = sum('plays')
  return plays ? sum(metric.id === 'rate' ? 'likes' : 'completed') / plays * 100 : null
}
export function format(value: number | null, metric: Metric) { return value === null ? '待填报' : `${value.toFixed(metric.decimals ?? 0)}${metric.unit === '%' ? '%' : ` ${metric.unit}`}` }
export function delta(value: number | null, reference: number | null, metric: Metric) {
  if (value === null || reference === null) return '暂无对比'
  const change = value - reference
  return `${change > 0 ? '+' : ''}${change.toFixed(metric.decimals ?? 0)} ${metric.unit === '%' ? '个百分点' : metric.unit}`
}
export function latestDate(goal: Goal) { return Object.keys(goal.observations).sort().at(-1) ?? TODAY }
