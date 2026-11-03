import type { CycleDefinition, CycleObservation } from './okr-execution-cycle'

export const promotionDefinition: CycleDefinition = {
  kind:'promotion',objective:'让更多开发者了解 Roami 并愿意关注和复用项目',longResult:'八周净增 100 star、20 fork（建议目标，需确认）',shortResult:'X 每周 3 篇图文为建议节奏；B站每天 1 条带配音的 Roami 小技巧',experiment:'两条内容线共用群聊与看板。每轮只调整展示结果、讲解结构或仓库入口中的一个因素，曝光与仓库增长分别衡量。',
  metricName:'GitHub star',unit:'star',target:100,baseline:120,direction:'up',
  projects:[{id:'roami-promotion',name:'Roami 宣传',directory:'/workspace/roami-promotion',git:false,contribution:'X 图文、截图、配音、字幕、视频、发布凭据与渠道记录'},{id:'roami',name:'Roami 仓库',directory:'/workspace/roami',git:true,contribution:'验证技巧、维护演示与数据连接；宣传任务不直接改动 main'}],
  actions:[
    {id:'x-post',agent:'X 图文智能体',projectId:'roami-promotion',title:'制作一篇英文 X 图文，展示持久会话的使用场景',artifact:'x-post-en.md + session-shot.png + 发布回执（回放）',acceptance:'英文易懂、截图来自已验证功能、仓库链接正确；发布遵循既有授权，未授权保留待发布',preview:'A useful Roami habit: name a persistent work session so you can find it tomorrow.\n配图：会话命名后的界面（需实际验证）。\n仓库入口：https://github.com/ybz21/Roami\n保存 post_id、发布时间、素材版本与发布凭据；这里不真实发帖。'},
    {id:'bili-tip',agent:'B站视频智能体',projectId:'roami-promotion',title:'制作今日 Roami 小技巧：给会话命名，附中文配音',artifact:'tip-01-script.md + voice-01.wav + captions-01.srt + tip-01.mp4 + 发布回执（回放）',acceptance:'每天一个技巧；录屏步骤可复现，中文配音与画面同步、字幕清楚，简介有仓库入口；记录 BVID 与发布状态',preview:'片长约 45 秒。\n0–5 秒配音：会话太多找不到？给 Roami 会话起个名字。\n5–30 秒录屏：找到目标会话，修改名称，再次定位。\n30–45 秒配音：下次打开还能找到同一个工作现场。简介附仓库入口。\n交付录屏、配音、字幕和合成视频；这里仅回放产物清单。'},
  ],
}
export function promotionFacts(date:string): Partial<CycleObservation> {
  if (date === '2026-11-11') return {value:120,forks:18}
  return date === '2026-11-12' ? {value:128,forks:19,xViews:1800,biliPlays:400,biliCompleted:104,biliWatchSeconds:6400} : {value:125,forks:21,xViews:2200,xClicks:44,biliPlays:600,biliCompleted:192,biliWatchSeconds:11400}
}
export const promotionNextActions = {'x-post':'X 下一轮先展示使用结果，保留仓库入口并补齐链接点击观测','bili-tip':'制作下一条带配音技巧：断开后继续同一会话；保持片长，只调整前 5 秒展示'}
