import { cycleActions, cycleDefinitions, CycleKind, latestCycleReview, activeCyclePlan } from './okr-execution-cycle'
import { DialogueScene, sceneSnapshot, dialogueScenes } from './okr-dialogue-scenes'

export type SwarmTask = { id: string; title: string; member: string; project: string; output: string; state: 'waiting'|'working'|'done' }
function projectSwarm(kind: CycleKind, scene: DialogueScene) {
  const state = sceneSnapshot(kind,scene), definition = cycleDefinitions[kind]
  const delivered = state.delivered[state.activeDate] ?? [], observation = state.observations.find(row => row.date === state.activeDate)
  const review = latestCycleReview(state), nextDate = new Date(Date.parse(`${state.activeDate}T12:00:00Z`)+86400000).toISOString().slice(0,10)
  const nextPlan = state.plans.findLast(plan => plan.date === nextDate)
  const tasks: SwarmTask[] = cycleActions(state,kind).map(action => ({id:`${state.activeDate}:${action.id}`,title:action.title,member:'执行',project:definition.projects.find(project => project.id === action.projectId)!.name,output:action.artifact,state:delivered.includes(action.id) ? 'done' : scene.id === 'activate' ? 'waiting' : 'working'}))
  tasks.push({id:`${state.activeDate}:data`,title:'核对来源并回填本轮观测',member:'数据',project:'已绑定数据来源',output:observation ? `${observation.value}${definition.unit} / ${observation.date}` : '带账号、日期、环境与回执的观测',state:observation ? 'done' : delivered.length ? 'working' : 'waiting'})
  tasks.push({id:`${state.activeDate}:review`,title:'分析当前证据，形成复盘建议',member:'复盘',project:'共享看板与证据',output:review?.decision ?? '事实、缺项、候选解释与下一步',state:review ? 'done' : observation ? 'working' : 'waiting'})
  tasks.push({id:`${state.activeDate}:adjust`,title:'把复盘接入下一轮执行',member:'主责',project:'目标与计划',output:nextPlan?.focus ?? '有 Review 来源的新计划',state:nextPlan ? 'done' : review ? 'working' : 'waiting'})
  const members = [
    {name:'主责',duty:'持续规划、分工与巡检',state:scene.id === 'activate' ? '就绪，等待规划触发' : nextPlan ? '下一轮计划已形成' : review ? '准备调整执行' : '协调本轮与依赖'},
    {name:'执行',duty:kind === 'creator' ? '脚本、制作、验收和发布记录' : '实现、回归、PR 与验证',state:delivered.length ? '本轮已交付，等待下一任务' : scene.id === 'activate' ? '等待任务' : '执行与验收中'},
    {name:'数据',duty:'维护连接与日期观测',state:observation ? '本轮已回填，按窗口继续采集' : delivered.length ? '准备读取与校验' : '等待事件或观测窗口'},
    {name:'复盘',duty:'独立分析，提出调整',state:review ? '本轮复盘已提交' : observation ? '接棒分析' : '等待本轮证据'},
  ]
  const id = kind === 'creator' ? 'content-growth-swarm' : 'pocketboard-swarm'
  const loop: {id:string;title:string;agent:string;status:'waiting'|'working'|'done'|'ready';output:string}[] = [
    {id:'execute',title:'执行',agent:'执行智能体',status:delivered.length ? 'done' : scene.id === 'activate' ? 'waiting' : 'working',output:'产物与验收'},
    {id:'observe',title:'取数',agent:'数据智能体',status:observation ? 'done' : delivered.length ? 'working' : 'waiting',output:'日期事实'},
    {id:'reflect',title:'反思',agent:'反思智能体',status:review ? 'done' : observation ? 'working' : 'waiting',output:'事实与调整建议'},
    {id:'adjust',title:'调整',agent:'主责智能体',status:nextPlan ? 'done' : review ? 'working' : 'waiting',output:'有来源的新计划'},
    {id:'execute-again',title:'再执行',agent:'执行智能体',status:nextPlan ? 'ready' : 'waiting',output:nextPlan ? `${nextPlan.date} 接棒` : '等待反思与计划'},
  ]
  return {id,boardId:`${id}:board`,roomId:`${id}:room`,state,definition,tasks,allTasks:tasks,members:members.map((member,index)=>({...member,id:`${id}:agent-${index+1}`})),review,nextPlan,observation,loop,inheritedPlan:activeCyclePlan(state)}
}

export function swarmProjection(kind:CycleKind,scene:DialogueScene) {
  const current = projectSwarm(kind,scene)
  const previous = scene.day === 2 ? projectSwarm(kind,{...scene,id:'carry',day:1,checkpoint:'next'}).tasks : []
  return {...current,allTasks:[...previous,...current.tasks]}
}

export type SwarmMessage = { id:string; sceneId:string; author:string; text:string; taskId?:string; date:string; facts?:string[] }
export function swarmMessages(kind:CycleKind,scene:DialogueScene): SwarmMessage[] {
  const scenes = dialogueScenes[kind], stop = scenes.findIndex(item=>item.id===scene.id)
  const messages: SwarmMessage[] = []
  for (const item of scenes.slice(0,stop+1).filter(item=>item.checkpoint)) {
    const projection = swarmProjection(kind,item), date = projection.state.activeDate
    const add = (author:string,text:string,taskId?:string) => messages.push({id:`${item.id}:${messages.length}`,sceneId:item.id,author,text,taskId,date})
    add('你',item.user)
    if (item.id === 'activate') { add('主责智能体','已建立同一群聊和共享看板。执行、数据、反思智能体在这里接力，所有任务、观测和结论写回这张看板。');continue }
    if (item.checkpoint === 'assigned') {
      const task = projection.tasks.find(task=>task.member==='执行')!
      add('主责智能体',`@执行智能体 请领取「${task.title}」，验收后把产物写回共享看板。`,task.id)
      add('执行智能体','已领取任务，按验收约定开始执行；完成后在群里报产物，并交给数据智能体。',task.id)
    } else if (item.checkpoint === 'delivered') {
      const task = projection.tasks.find(task=>task.member==='执行')!
      add('执行智能体',`已回填产物与验收：${task.output}。@数据智能体 请核对来源与观察窗口；业务效果仍待采集。`,task.id)
    } else if (item.checkpoint === 'observed') {
      add('数据智能体',`已校验并写回 ${date} 的真实观测回放：${projection.observation!.value}${projection.definition.unit}。@反思智能体 请结合共享看板原始数、窗口和产物分析。`,`${date}:data`)
    } else if (item.checkpoint === 'reviewed') {
      if (item.view === 'decision') add('主责智能体','这份反思已在共享看板。你可以在群里决定继续、调整或暂停；决定与本轮证据一起保留。',`${date}:adjust`)
      else {
        if (item.day === 2) add('数据智能体',`本轮 ${date} 观测已写回共享看板，交给反思智能体。`,`${date}:data`)
        add('反思智能体',`已读共享看板的任务与观测。判断：${projection.review!.decision} 建议：${projection.review!.nextAction}`,`${date}:review`)
        messages[messages.length-1].facts=projection.review!.facts
        add('主责智能体','收到反思。下一轮计划将引用这份证据，不改写历史或重复已交付任务。',`${date}:adjust`)
      }
    } else if (item.checkpoint === 'next') {
      add('主责智能体',`已采用本轮反思，写入 ${projection.nextPlan!.date} 计划：${projection.nextPlan!.focus}。@执行智能体 请带着这份结论继续。`,`${date}:adjust`)
      add('执行智能体','已收到下一轮计划与反思来源，等待约定时机接棒；沿用同一张看板和这个群。')
    }
  }
  return messages
}
