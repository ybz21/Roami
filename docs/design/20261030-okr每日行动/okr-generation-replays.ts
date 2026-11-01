import { BrowserObservation, GeneratedPlan, BrowserConnector } from './okr-generation-contract'

const consoleSource: BrowserConnector = {
  id:'creator-console', revision:2, name:'创作者后台读取', method:'browser', origin:'https://127.0.0.1:18684', path:'/fixtures/creator-console.html',
  expectedAccountId:'demo-creator', account:{ selector:'#account',attribute:'data-account-id' }, date:{ selector:'#observation-date',attribute:'datetime' },
  fields:[{ id:'audience',unit:'人',selector:'[data-field="audience"]' },{ id:'likes',unit:'次',selector:'[data-field="likes"]' },{ id:'plays',unit:'次',selector:'[data-field="plays"]' },{ id:'completed',unit:'次',selector:'[data-field="completed"]' },{ id:'watch-seconds',unit:'秒',selector:'[data-field="watch-seconds"]' }],
}
export const growthReplay: GeneratedPlan = {
  schemaVersion:1, revision:1, cycleStart:'2026-11-12', statement:'八周内让我的 AI 编程栏目多 200 个真实粉丝，每天帮我推进。', objective:'让 AI 编程内容被看下去并持续获得真实关注',
  rationale:'分别衡量粉丝增长、完播率和平均观看时长；发布与验收是推进手段。观看质量与涨粉独立核验，不互相代替。',
  assumptions:['粉丝基线尚未读取，不填写总量目标。','完播率 30%、平均观看 18 秒是待你确认的建议目标，实际基线待读取；仅用于本例约 45 秒视频。','建议每周发布两次，需与你确认时间是否合适。'],
  keyResults:[
    { id:'audience-growth',title:'八周净增 200 个真实粉丝',view:'number',horizon:'long',period:{start:'2026-11-12',end:'2027-01-06'},target:200,unit:'人',metricId:'audience-net',rationale:'直接回答关注增长是否发生，不把发布数量当涨粉。' },
    { id:'completion-quality',title:'八周内同口径完播率达到 30%',view:'number',horizon:'long',period:{start:'2026-11-12',end:'2027-01-06'},target:30,unit:'%',metricId:'completion-rate',rationale:'观看质量本身是结果；先确认平台有效播放与完整播放口径，按日持续追踪，不用涨粉代替。' },
    { id:'watch-quality',title:'八周内平均观看时长达到 18 秒',view:'number',horizon:'long',period:{start:'2026-11-12',end:'2027-01-06'},target:18,unit:'秒',metricId:'average-watch',rationale:'衡量观众实际看了多久，区别于视频片长；与完播率独立判断，目标须在核对片长和实际基线后确认。' },
    { id:'publishing-loop',title:'跑通可持续的内容生产流程',view:'milestones',horizon:'short',parentKrId:'audience-growth',period:{start:'2026-11-12',end:'2026-11-25'},items:['完成一个可复现的 AI 编程案例','发布第一期图文与短视频','连续两周按约定节奏交付'],rationale:'这是支持长期增长的短期交付建议；阶段验收与真实涨粉分别衡量。' },
  ],
  metrics:[
    { id:'audience-total',krId:'audience-growth',name:'粉丝总量',unit:'人',connectorId:'creator-console',formula:{ op:'field',field:'audience' },rationale:'保留账号规模的每日快照，为增长计算提供原始数。' },
    { id:'audience-net',krId:'audience-growth',name:'周期净增',unit:'人',connectorId:'creator-console',formula:{ op:'difference',field:'audience',baseline:null },rationale:'当天总量减有效周期起点；当前没有起点时保持未知。' },
    { id:'completion-rate',krId:'completion-quality',name:'当日完播率',unit:'%',connectorId:'creator-console',formula:{ op:'ratio',numerator:'completed',denominator:'plays' },rationale:'完整播放量 / 同口径有效播放量；保留原始分子分母、日期和样本量，变化以百分点展示。' },
    { id:'average-watch',krId:'watch-quality',name:'平均观看时长',unit:'秒',connectorId:'creator-console',formula:{ op:'average',numerator:'watch-seconds',denominator:'plays' },rationale:'同窗口总观看秒数 / 对应有效播放量；按日留存，变化以秒展示。跨日先合计总时长和播放量，不平均各天的均值。' },
  ],
  connectors:[{ ...consoleSource,revision:1,fields:consoleSource.fields.filter(field => field.id !== 'likes') }],
  widgets:[
    { id:'growth-card',type:'metric',title:'增长结果',metricIds:['audience-net'] },
    { id:'audience-line',type:'trend',title:'粉丝按日变化',metricIds:['audience-total'] },
    { id:'completion-card',type:'metric',title:'完播率 / 目标 30%',metricIds:['completion-rate'] },
    { id:'watch-card',type:'metric',title:'平均观看时长 / 目标 18 秒',metricIds:['average-watch'] },
    { id:'quality-line',type:'trend',title:'观看质量按日变化',metricIds:['completion-rate','average-watch'] },
    { id:'production-checks',type:'checks',title:'内容流程验收',krId:'publishing-loop',metricIds:[] },
    { id:'daily-records',type:'records',title:'日期与来源记录',metricIds:['audience-total','audience-net','completion-rate','average-watch'] },
  ],dailyAction:'结合完播率与平均观看时长改进开场、解释和剪辑；每轮只改一个因素，同龄复验后再决定，粉丝增长另行追踪。',
}
export const qualityReplay: GeneratedPlan = {
  ...growthReplay, revision:2, statement:`${growthReplay.statement} 我还想关注点赞率，并要求每次发布前有完整验收。`,
  rationale:'保留增长、完播率和平均观看时长三项结果 KR，新增点赞诊断和发布验收；短期验收不替代观看效果。',
  assumptions:[...growthReplay.assumptions,'示例点赞率采用同一日点赞量 / 有效播放量；真实平台口径须重新核对。'],
  keyResults:[...growthReplay.keyResults,{ id:'release-quality',title:'发布内容具备可复现性与清晰演示',view:'checklist',horizon:'short',parentKrId:'audience-growth',period:{start:'2026-11-12',end:'2026-11-18'},items:['代码可在干净环境运行','画面演示与步骤一致','发布文案和链接已核对'],rationale:'你新增的是验收要求，清单比百分比进度更合适。' }],
  metrics:[...growthReplay.metrics,{ id:'engagement-rate',krId:'audience-growth',name:'当日点赞率',unit:'%',connectorId:'creator-console',formula:{ op:'ratio',numerator:'likes',denominator:'plays' },rationale:'作为增长诊断，不能仅凭相关性断定点赞导致涨粉。' }],
  connectors:[consoleSource],
  widgets:[...growthReplay.widgets.slice(0,5),{ id:'engagement',type:'metric',title:'互动诊断',metricIds:['engagement-rate'] },{ id:'release-checks',type:'checks',title:'发布验收',metricIds:[],krId:'release-quality' },...growthReplay.widgets.slice(5)],
}
export const repoReplay: GeneratedPlan = {
  schemaVersion:1,revision:1,cycleStart:'2026-11-12',statement:'八周内把 PocketBoard 做成可用的 repo，持续维护功能，发布版 API p95 降到 300ms。',objective:'让 PocketBoard 可用、响应快且持续可维护',
  rationale:'把可用功能、发布版性能与维护底线分别衡量；一次开发分支测试不能代表发布结果。',
  assumptions:['性能基准需固定版本、负载与环境。','以下连接描述是样例，未接入真实监控。'],
  keyResults:[
    { id:'release-ready',title:'发布可完成核心流程的版本',view:'milestones',items:['创建和编辑任务','搜索和筛选可用','发布版端到端复验'],rationale:'交付结果分阶段验收。' },
    { id:'latency-result',title:'发布版 API p95 不高于 300ms',view:'number',metricId:'release-latency',target:300,unit:'ms',rationale:'使用固定负载下的发布版基准，不用开发分支候选结果。' },
    { id:'maintenance-ready',title:'具备持续维护的回归与恢复能力',view:'checklist',items:['核心路径进入回归','发布具备回滚步骤','故障有定位记录'],rationale:'维护能力用可验证清单呈现，不能凭一次性能数值代替。' },
  ],
  metrics:[{ id:'release-latency',krId:'latency-result',name:'发布版 p95',unit:'ms',connectorId:'release-monitor',formula:{ op:'field',field:'latency' },rationale:'只读取同一环境和负载的发布版 p95 统计。' }],
  connectors:[{ id:'release-monitor',name:'发布监控读取',revision:1,method:'browser',origin:'https://monitor.example.invalid',path:'/releases',expectedAccountId:'pocketboard-demo',account:{ selector:'[data-project]',attribute:'data-project' },date:{ selector:'time',attribute:'datetime' },fields:[{ id:'latency',unit:'ms',selector:'[data-field="release-p95"]' }] }],
  widgets:[{ id:'latency',type:'metric',title:'性能结果',metricIds:['release-latency'] },{ id:'release-checks',type:'checks',title:'功能验收',krId:'release-ready',metricIds:[] },{ id:'latency-line',type:'trend',title:'发布版性能变化',metricIds:['release-latency'] },{ id:'maintenance-checks',type:'checks',title:'维护底线',krId:'maintenance-ready',metricIds:[] }],
  dailyAction:'先完成核心任务流程，再以固定负载验证发布候选；发布后独立复验。',
}
export const replayOptions = [{ label:'内容增长',plan:growthReplay },{ label:'项目维护',plan:repoReplay }]
export function replayObservation(plan: GeneratedPlan, date = '2026-11-11'): BrowserObservation {
  const c = plan.connectors[0]
  const values: Record<string,{value:number;unit:string}> = c.id === 'creator-console' ? { audience:{ value:date === '2026-11-11' ? 328 : 334,unit:'人' },likes:{ value:40,unit:'次' },plays:{ value:date === '2026-11-11' ? 600 : 700,unit:'次' },completed:{ value:date === '2026-11-11' ? 144 : 224,unit:'次' },'watch-seconds':{ value:date === '2026-11-11' ? 8400 : 12600,unit:'秒' } } : { latency:{ value:date === '2026-11-11' ? 720 : 690,unit:'ms' } }
  return { connectorId:c.id,connectorRevision:c.revision,accountId:c.expectedAccountId,date,capturedAt:`${date}T13:00:00Z`,sourceUrl:`${c.origin}${c.path}`,evidenceKind:'replay',values:Object.fromEntries(c.fields.map(f => [f.id,values[f.id]])) }
}
