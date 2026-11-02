import type { BrowserConnector, GeneratedPlan } from './okr-generation-contract'
const source = (id:string,name:string,account:string,fields:{id:string;unit:string}[]):BrowserConnector => ({id,name,revision:1,method:'browser',origin:'https://127.0.0.1:18684',path:'/fixtures/roami-promotion-console.html',expectedAccountId:account,account:{selector:`#${id}-account`,attribute:'data-account-id'},date:{selector:'#promotion-date',attribute:'datetime'},fields:fields.map(field=>({...field,selector:`[data-field="${field.id}"]`}))})
export const promotionReplay: GeneratedPlan = {
  schemaVersion:1,revision:1,cycleStart:'2026-11-12',statement:'宣传 Roami：在 X 发英文图文，每天录一个带配音的小技巧发 B站，目标增加 GitHub star 和 fork。',objective:'让更多开发者了解 Roami 并愿意关注和复用项目',
  rationale:'star、fork 是两项独立结果；X 图文和 B站配音技巧视频是两条推进路径。播放、完播和点击是诊断，不直接换成 star/fork。',
  assumptions:['八周净增 100 star、20 fork 是待确认建议；示例起点不代表真实仓库现状。','B站每天一个带配音的小技巧来自你的要求；X 每周三篇为可调整建议。','真实接入优先使用已有 GitHub 工具/API；这里的三个来源均为本地夹具或回放，不访问账号。','链接点击权限与归因数据需实查，未提供时保持未知。'],
  keyResults:[
    {id:'roami-stars',title:'八周净增 100 star（建议）',view:'number',horizon:'long',period:{start:'2026-11-12',end:'2027-01-06'},metricId:'stars-net',target:100,unit:'star',rationale:'关注仓库的实际增长，每日同一仓库快照减有效起点；允许取消 star 导致负增量。'},
    {id:'roami-forks',title:'八周净增 20 fork（建议）',view:'number',horizon:'long',period:{start:'2026-11-12',end:'2027-01-06'},metricId:'forks-net',target:20,unit:'fork',rationale:'单独衡量 fork 增长，不与 star 混成一个总分，也不把 fork 当成已深度使用。'},
    {id:'promotion-loop',title:'跑通两条可持续宣传路径',view:'milestones',horizon:'short',parentKrId:'roami-stars',period:{start:'2026-11-12',end:'2026-11-18'},items:['X 英文图文：场景、真实截图与仓库入口','B站每天一个 Roami 小技巧：录屏、中文配音、字幕与视频','逐条记录发布状态、内容 ID、来源与反馈'],rationale:'内容交付是支持结果的短期工作，发布完成不代表增长结果达成。'},
  ],
  connectors:[source('roami-repo','GitHub 仓库快照夹具','ybz21/Roami',[{id:'stars',unit:'star'},{id:'forks',unit:'fork'}]),source('roami-x','X 内容记录夹具','roami-demo-x',[{id:'x-views',unit:'次'},{id:'x-clicks',unit:'次'}]),source('roami-bili','B站视频记录夹具','roami-demo-bili',[{id:'bili-plays',unit:'次'},{id:'bili-completed',unit:'次'},{id:'bili-watch-seconds',unit:'秒'}])],
  metrics:[
    {id:'stars-total',krId:'roami-stars',name:'star 总量',unit:'star',connectorId:'roami-repo',formula:{op:'field',field:'stars'},rationale:'同一仓库、日期与采集时刻的快照。'},
    {id:'stars-net',krId:'roami-stars',name:'周期 star 净增',unit:'star',connectorId:'roami-repo',formula:{op:'difference',field:'stars',baseline:null},rationale:'快照减有效周期起点，不将缺失日期补成零。'},
    {id:'forks-total',krId:'roami-forks',name:'fork 总量',unit:'fork',connectorId:'roami-repo',formula:{op:'field',field:'forks'},rationale:'fork 独立保存，不能用 star 增长代替。'},
    {id:'forks-net',krId:'roami-forks',name:'周期 fork 净增',unit:'fork',connectorId:'roami-repo',formula:{op:'difference',field:'forks',baseline:null},rationale:'fork 快照减有效起点；快照净变化不是新增 fork 事件数。'},
    {id:'x-exposure',krId:'promotion-loop',name:'X 曝光（诊断）',unit:'次',connectorId:'roami-x',formula:{op:'field',field:'x-views'},rationale:'保留 post ID 和平台窗口，帮助判断图文是否被看见。'},
    {id:'x-link-clicks',krId:'promotion-loop',name:'X 链接点击（诊断）',unit:'次',connectorId:'roami-x',formula:{op:'field',field:'x-clicks'},rationale:'需要后台权限或自有落地页观测；不可从曝光或 star 倒推。'},
    {id:'bili-completion',krId:'promotion-loop',name:'B站完播率（诊断）',unit:'%',connectorId:'roami-bili',formula:{op:'ratio',numerator:'bili-completed',denominator:'bili-plays'},rationale:'同一 BVID、观察窗口与播放集合的完整播放/有效播放，实际口径须核对。'},
    {id:'bili-average',krId:'promotion-loop',name:'B站平均观看时长（诊断）',unit:'秒',connectorId:'roami-bili',formula:{op:'average',numerator:'bili-watch-seconds',denominator:'bili-plays'},rationale:'同窗口总观看秒数/对应播放量；与视频片长分别保存。'},
  ],
  widgets:[{id:'stars-card',type:'metric',title:'star 结果',metricIds:['stars-net']},{id:'forks-card',type:'metric',title:'fork 结果',metricIds:['forks-net']},{id:'stars-line',type:'trend',title:'star 日期波动',metricIds:['stars-total']},{id:'forks-line',type:'trend',title:'fork 日期波动',metricIds:['forks-total']},{id:'content-checks',type:'checks',title:'两条内容线的交付',krId:'promotion-loop',metricIds:[]},{id:'channel-records',type:'records',title:'渠道反馈与缺项',metricIds:['x-exposure','x-link-clicks','bili-completion','bili-average']},{id:'repo-records',type:'records',title:'仓库日期与来源',metricIds:['stars-total','forks-total']}],
  dailyAction:'主责在共享群派发：X 图文智能体制作英文图文，B站视频智能体录屏、配音与合成；数据回填后独立反思，再调整下一轮。',
}
export const promotionQualityReplay: GeneratedPlan = {...promotionReplay,revision:2,keyResults:[...promotionReplay.keyResults,{id:'voiced-tip-quality',title:'每日技巧视频可复现且配音清楚',view:'checklist',horizon:'short',parentKrId:'roami-stars',period:{start:'2026-11-12',end:'2026-11-18'},items:['一个真实可复现的 Roami 小技巧','录屏、中文配音与字幕同步','标题、简介、仓库链接与发布回执齐全'],rationale:'对内容产物逐条验收，不将日更数量当作 star/fork 结果。'}],widgets:[...promotionReplay.widgets,{id:'voiced-tip-checks',type:'checks',title:'每日配音技巧验收',krId:'voiced-tip-quality',metricIds:[]}]}
