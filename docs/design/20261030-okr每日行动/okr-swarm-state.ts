import { cycleActions, cycleDefinitions, CycleKind, latestCycleReview } from './okr-execution-cycle'
import { DialogueScene, sceneSnapshot } from './okr-dialogue-scenes'

type SwarmTask = { id: string; title: string; member: string; project: string; output: string; state: 'waiting'|'working'|'done' }
export function swarmProjection(kind: CycleKind, scene: DialogueScene) {
  const state = sceneSnapshot(kind,scene), definition = cycleDefinitions[kind]
  const delivered = state.delivered[state.activeDate] ?? [], observation = state.observations.find(row => row.date === state.activeDate)
  const review = latestCycleReview(state), nextDate = new Date(Date.parse(`${state.activeDate}T12:00:00Z`)+86400000).toISOString().slice(0,10)
  const nextPlan = state.plans.findLast(plan => plan.date === nextDate)
  const tasks: SwarmTask[] = cycleActions(state,kind).map(action => ({id:action.id,title:action.title,member:'执行',project:definition.projects.find(project => project.id === action.projectId)!.name,output:action.artifact,state:delivered.includes(action.id) ? 'done' : scene.id === 'activate' ? 'waiting' : 'working'}))
  tasks.push({id:'data',title:'核对来源并回填本轮观测',member:'数据',project:'已绑定数据来源',output:observation ? `${observation.value}${definition.unit} / ${observation.date}` : '带账号、日期、环境与回执的观测',state:observation ? 'done' : delivered.length ? 'working' : 'waiting'})
  tasks.push({id:'review',title:'分析当前证据，形成复盘建议',member:'复盘',project:'共享看板与证据',output:review?.decision ?? '事实、缺项、候选解释与下一步',state:review ? 'done' : observation ? 'working' : 'waiting'})
  tasks.push({id:'adjust',title:'把复盘接入下一轮执行',member:'主责',project:'目标与计划',output:nextPlan?.focus ?? '有 Review 来源的新计划',state:nextPlan ? 'done' : review ? 'working' : 'waiting'})
  const members = [
    {name:'主责',duty:'持续规划、分工与巡检',state:scene.id === 'activate' ? '就绪，等待规划触发' : nextPlan ? '下一轮计划已形成' : review ? '准备调整执行' : '协调本轮与依赖'},
    {name:'执行',duty:kind === 'creator' ? '脚本、制作、验收和发布记录' : '实现、回归、PR 与验证',state:delivered.length ? '本轮已交付，等待下一任务' : scene.id === 'activate' ? '等待任务' : '执行与验收中'},
    {name:'数据',duty:'维护连接与日期观测',state:observation ? '本轮已回填，按窗口继续采集' : delivered.length ? '准备读取与校验' : '等待事件或观测窗口'},
    {name:'复盘',duty:'独立分析，提出调整',state:review ? '本轮复盘已提交' : observation ? '接棒分析' : '等待本轮证据'},
  ]
  return {id:kind === 'creator' ? 'content-growth-swarm' : 'pocketboard-swarm',state,definition,tasks,members,review,nextPlan,observation}
}
