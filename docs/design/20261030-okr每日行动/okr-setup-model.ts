import { creatorMetrics, Goal, Metric, repoMetrics, repoStatement, Snapshot, previous } from './prototype-data'

export type KeyResult = { id: string; title: string; enabled: boolean; target: number }
export type Binding = {
  platform: string; method: 'browser' | 'api' | 'import'; entry: string; account: string;
  status: 'idle' | 'login' | 'failed' | 'sample' | 'bound'; scenario: 'ready' | 'login' | 'failed' | 'partial';
  sample?: Snapshot; accountId?: string; checkedAt?: string; evidence?: string; importSample: boolean;
}
export type SetupDraft = {
  boardTitle: string; showTrend: boolean; kind: Goal['kind']; statement: string; title: string;
  start: string; end: string; minutes: number; daily: boolean; keyResults: KeyResult[];
  candidates: Metric[]; metrics: Metric[]; metricsConfirmed: boolean; binding: Binding;
}
export const entryFor = (platform: string) => platform === '抖音' ? 'https://creator.douyin.com/' : platform === '视频号' ? 'https://channels.weixin.qq.com/' : '本机 PocketBoard 项目'
export function starter(kind: Goal['kind'], platform = '视频号'): SetupDraft {
  return {
    boardTitle: kind === 'creator' ? `${platform}增长看板` : 'PocketBoard 维护看板', showTrend: true, kind,
    statement: kind === 'creator' ? `帮我提升${platform}的粉丝量，持续分享 AI 编程。我想同时关注点赞量、点赞率、完播率和平均观看时长，每天自动更新数据。` : repoStatement,
    title: kind === 'creator' ? `让${platform}持续获得关注，内容有人看完、愿意互动` : '让 PocketBoard 可日常使用、响应快且持续可维护',
    start: '2026-11-12', end: '2027-01-06', minutes: kind === 'creator' ? 30 : 60, daily: true,
    keyResults: kind === 'creator' ? [
      { id: 'growth', title: '本周期增加真实关注者', enabled: true, target: 200 },
      { id: 'engagement', title: '提升内容互动', enabled: true, target: 300 },
      { id: 'retention', title: '提升完播率', enabled: true, target: 40 },
      { id: 'watch-time', title: '提升平均观看时长（秒）', enabled: true, target: 18 },
    ] : [
      { id: 'journey', title: '发布版核心旅程通过验收', enabled: true, target: 4 },
      { id: 'performance', title: '降低看板 API p95 响应时间', enabled: true, target: 300 },
      { id: 'usage', title: '四位试用者连续四周有效使用', enabled: true, target: 4 },
    ],
    candidates: [], metrics: [], metricsConfirmed: false,
    binding: { platform: kind === 'creator' ? platform : '本机项目', method: 'browser', entry: entryFor(kind === 'creator' ? platform : '本机项目'), account: '', status: 'idle', scenario: 'ready', importSample: true },
  }
}
export function analyze(draft: SetupDraft): Metric[] {
  const enabled = draft.keyResults.filter(kr => kr.enabled)
  if (draft.kind === 'repo') return repoMetrics.filter((_, i) => enabled.some(kr => kr.id === ['journey', 'performance', 'usage'][i])).map(m => ({ ...m, krId: { journeys: 'journey', p95: 'performance', retained: 'usage' }[m.id], baselineKnown: false, source: '待接入数据' }))
  const target = enabled.find(kr => kr.id === 'growth')?.target ?? 200
  const metrics: Metric[] = [
    { ...creatorMetrics[0], name: '粉丝总量', channel: draft.binding.platform, baseline: 0, target, baselineKnown: false, krId: 'growth', role: '结果', rationale: '衡量账号规模；先读取实际起点，再把净增目标换成总量目标。', source: '待接入数据' },
    { id: 'netFollowers', name: '周期净增粉丝', unit: '人', baseline: 0, target, direction: 'up', channel: draft.binding.platform, window: '本周期', krId: 'growth', role: '派生', rationale: '排除起点差异，直接观察涨粉 KR 的差距；依赖粉丝总量和有效基线。', source: '粉丝总量减周期基线', baselineKnown: true },
    { ...creatorMetrics[1], channel: draft.binding.platform, krId: 'engagement', role: '结果', rationale: '观察互动规模，避免只看比例却忽略实际互动人数。', target: enabled.find(kr => kr.id === 'engagement')?.target ?? 300, baselineKnown: false, source: '待接入数据' },
    { ...creatorMetrics[2], channel: draft.binding.platform, krId: 'engagement', role: '诊断', rationale: '结合播放规模判断互动质量，避免把曝光增加误当成互动意愿改善。', baselineKnown: false, source: '点赞量 / 同口径有效播放量' },
    { ...creatorMetrics[3], channel: draft.binding.platform, krId: 'retention', role: '结果', rationale: '判断观众是否看下去；分母和时间窗口必须明确。', target: enabled.find(kr => kr.id === 'retention')?.target ?? 40, baselineKnown: false, source: '完整播放量 / 同口径有效播放量' },
    { ...creatorMetrics[4], channel: draft.binding.platform, krId: 'watch-time', role: '结果', rationale: '衡量实际观看秒数，区别于视频片长；与完播率分别衡量。', target: enabled.find(kr => kr.id === 'watch-time')?.target ?? 18, baselineKnown: false, source: '同窗口总观看秒数 / 有效播放量' },
  ]
  return metrics.filter(m => enabled.some(kr => kr.id === m.krId))
}
export function hasField(binding: Binding, metric: Metric) {
  const sample = binding.sample
  if (!sample || binding.status !== 'bound') return false
  const keys = ({ followers: ['followers'], netFollowers: ['followers'], likes: ['likes'], rate: ['likes', 'plays'], completion: ['completed', 'plays'], averageWatch: ['watchSeconds', 'plays'], journeys: ['journeys'], p95: ['p95'], retained: ['retained'] } as Record<string, string[]>)[metric.id] ?? []
  return keys.length > 0 && keys.every(key => (sample as unknown as Record<string, unknown>)[key] !== undefined)
}
export function bindMetrics(draft: SetupDraft): Metric[] {
  return draft.metrics.map(metric => {
    const rawReady = hasField(draft.binding, metric)
    const validStart = !!draft.binding.sample && [draft.start,previous(draft.start)].includes(draft.binding.sample.date)
    const ready = rawReady && (metric.id !== 'netFollowers' || validStart)
    const baseline = ready && metric.id === 'followers' ? draft.binding.sample!.followers! : metric.baseline
    return {
      ...metric, channel: draft.binding.platform, source: ready ? `${draft.binding.platform} / ${draft.binding.account} / ${metric.id === 'netFollowers' ? '已验证粉丝总量减起点' : metric.id === 'rate' ? '点赞量与播放量' : metric.id === 'completion' ? '完整播放量与播放量' : '已验证原始字段'}` : '待接入数据',
      baseline, target: metric.id === 'followers' && ready ? baseline + (draft.keyResults.find(kr => kr.id === 'growth')?.target ?? 200) : metric.target,
      baselineKnown: metric.id === 'followers' ? ready && validStart : metric.baselineKnown, targetKnown: metric.id === 'followers' ? ready && validStart : true, baselineDate: metric.id === 'followers' && ready ? draft.binding.sample!.date : metric.baselineDate,
      bindingState: ready ? 'bound' as const : 'pending' as const,
    }
  })
}
export const baselineText = (m: Metric) => m.baselineKnown === false ? '待取样建立' : `${m.baseline}${m.unit}`

export function requiredFacts(metrics: Metric[]): string[] {
  const fields: Record<string,string[]> = { followers:['followers'],netFollowers:['followers'],likes:['likes'],rate:['likes','plays'],completion:['completed','plays'],averageWatch:['watchSeconds','plays'],journeys:['journeys'],p95:['p95'],retained:['retained'] }
  return [...new Set(metrics.flatMap(m => fields[m.id] ?? []))]
}
