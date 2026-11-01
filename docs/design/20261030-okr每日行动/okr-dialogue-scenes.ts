import { applyNextPlan, collectCycleData, cycleDefinitions, CycleKind, CycleState, cycleActions, deliverAction, initialCycle, reviewCycle } from './okr-execution-cycle'
import { GeneratedPlan } from './okr-generation-contract'
import { growthReplay, qualityReplay, repoReplay } from './okr-generation-replays'

export const storylines = [
  { title:'1 聊 OKR', purpose:'说清方向、周期和投入，形成共同的目标约定。' },
  { title:'2 拆 KR 与看板', purpose:'由智能体提出长短 KR，再分析指标和关键看板。' },
  { title:'3 建好看板', purpose:'发现来源、生成连接、核对样本，保存可运行的看板。' },
  { title:'4 运转与决策', purpose:'职能接力执行，事件回填看板，反思后继续，人可随时决定。' },
] as const
export type DialogueView = 'intent'|'goals'|'metrics'|'source'|'board'|'projects'|'launch'|'handoff'|'work'|'review'|'decision'|'next'
export type CycleCheckpoint = 'assigned'|'delivered'|'observed'|'reviewed'|'next'
export type DialogueScene = { id: string; chapter: string; title: string; user: string; reply: string; caption: string; view: DialogueView; duration: number; revision: number; day?: 1|2; sampled?: boolean; action?: string; checkpoint?: CycleCheckpoint; intentConfirmed?: boolean }
const [talk,split,build,operate] = storylines.map(line => line.title)
export const dialogueScenes: Record<CycleKind,DialogueScene[]> = {
  creator:[
    {id:'goal',chapter:talk,title:'先聊想做成什么',user:'我想持续讲 AI 编程，教大家做公众号和短视频。希望 Roami 帮我长期推进。',reply:'先把方向聊清楚：你更想扩大内容影响力，还是获得有效咨询？准备做多久，每天能投入多少时间？现在先不要求你列 KR 或指标。',caption:'故事从一个还不完整的想法开始，先聊 OKR。',view:'intent',duration:9000,revision:1,action:'说清周期和期待'},
    {id:'clarify',chapter:talk,title:'把方向变成明确约定',user:'先扩大影响力。做八周，希望净增 200 个真实粉丝，每天我能投入半小时。',reply:'O 是让 AI 编程内容持续获得真实关注。八周净增 200 人是你明确的期待，日投入半小时是约束；实际粉丝起点还未知。接下来由我提出衡量和推进方案。',caption:'这一步只确认目标与约束，不提前假装 KR 和数据都已齐备。',view:'intent',intentConfirmed:true,duration:9000,revision:1,action:'请智能体拆分 KR'},
    {id:'kr-proposal',chapter:split,title:'智能体拆出第一版长短 KR',user:'按刚才聊的目标，帮我拆出 KR；短期也要能持续检查。',reply:'我提出两项：长期看八周净增 200 人；短期先跑通可持续内容交付。一个用数值结果，一个用阶段验收。它们是待你采用的建议，不需要你先填表。',caption:'先从目标拆 KR，长短结果的展现形式由含义决定。',view:'goals',duration:9000,revision:1,action:'补充本周实验与验收'},
    {id:'revise',chapter:split,title:'根据补充动态调整 KR',user:'本周先试更短的开场，也看点赞率。发布前的代码复现、字幕和链接都要验收。',reply:'保留长期增长方向，补充本周验收与互动诊断。方案从两条 KR 调整到三条，分别用数值、阶段和清单呈现；本周的开场实验另有观察窗口。',caption:'不是替换一段文案，而是 KR、指标需求和看板结构一起变化。',view:'goals',duration:9000,revision:2,action:'确认 KR，分析关键看板'},
    {id:'metrics',chapter:split,title:'从 KR 推导指标与关键看板',user:'这些 KR 可以。你分析一下需要哪些指标，关键看板怎么安排。',reply:'增长关联粉丝总量和周期净增，点赞率作诊断；交付保留验收清单。建议生成结果卡、日期趋势、验收和明细；单视频按 ID 与观察龄看完播。先确认这份衡量方案，再寻找数据。',caption:'第二条线走完：KR 对应什么指标，为什么需要这几块看板。',view:'metrics',duration:10000,revision:2,action:'确认指标，开始建看板'},
    {id:'discover',chapter:build,title:'先找到数据来源和连接方式',user:'这些指标确认。数据在视频号后台，我不知道接口，你先找可用方式。',reply:'先发现已授权能力，能用接口就用接口，页面可读则形成浏览器 connector。核对登录、账号、日期与字段；需要登录时请你去原后台完成，不把候选连接当成功。',caption:'建看板先解决数据怎么来，不只画一排空卡片。',view:'source',duration:9000,revision:2,action:'回放登录后的取样'},
    {id:'sample',chapter:build,title:'取样，验证字段和起点',user:'后台已登录，先只读取样，核对账号。',reply:'示例账号 demo-creator，11 月 11 日粉丝 328，周期从 12 日开始，可以建立增长基线。其他指标只有取得兼容字段后才接通；单视频观察龄还要单独核对。',caption:'用账号、日期和字段证据建立连接，不能靠模型猜数据。',view:'source',sampled:true,duration:9000,revision:2,action:'把看板生成出来'},
    {id:'board',chapter:build,title:'第一次生成可追溯的看板',user:'用已确认指标和样本生成整体看板，未接上的项保留待接入。',reply:'看板已在演示中形成：粉丝基线 328、净增起点 0，其他日期等待观测。结果、趋势、验收和明细都能反查 KR 与来源，不补造历史。',caption:'第三条线的产出是一张已保存、有来源、有缺失状态的整体看板。',view:'board',sampled:true,duration:10000,revision:2,action:'安排自动更新'},
    {id:'schedule',chapter:build,title:'把更新方式也约定好',user:'每天整理账号数据，视频到观察窗口再取数；异常告诉我，我也要随时查看。',reply:'账号每天更新，单视频按发布时间与观察龄采集；任务验收和新观测到达时就补充对应区域。来源失效保留旧记录并提示处理，界面显示每项实际更新时间。',caption:'不是等晚上改一个总进度，而是事件到达就更新，采集时机按指标约定。',view:'board',sampled:true,duration:9000,revision:2,action:'关联项目和职能'},
    {id:'projects',chapter:build,title:'给目标关联执行载体与职能',user:'素材放 AI 编程栏目，渲染和取数代码放内容自动化工具。由谁负责推进？',reply:'目标关联两个 project。主责管长短目标与计划；执行职能制作和验证产物；数据职能维护连接并填数；复盘职能独立分析。按任务接力，不必四个职能都常驻。',caption:'第四条线先交代组织方式：谁在什么项目里干什么。',view:'projects',duration:9000,revision:2,action:'启动长期 Swarm'},
    {id:'activate',chapter:operate,title:'搭建完成，启动长期 Swarm',user:'采用这版 KR、看板和项目分工，启动长期运行的 Swarm。',reply:'演示 Swarm 已建立，保留目标、已发布配置、成员职责与共享任务。界面切换到运行态：由主责持续巡检，成员按事件与时段接力，跨天沿用有效复盘。',caption:'搭建结束后，进入长期 Swarm 工作台；运行不再以搭建对话为主。',view:'launch',checkpoint:'assigned',day:1,duration:9000,revision:2,action:'让主责安排今天的动作'},
    {id:'assign',chapter:operate,title:'主责把近期假设交给执行职能',user:'今天先做 5 秒开场版本，主题和时长尽量保持。',reply:'主责派两项任务：素材项目制作视频，工具项目核对视频 ID 与 T+24h 口径。每项都带 KR、实验、验收和产物要求；数据职能等待发布或观测时机，复盘等待证据。',caption:'把职能分工画在当前任务上，而不是只列几个智能体名字。',view:'handoff',checkpoint:'assigned',day:1,duration:8000,revision:2,action:'回放执行与产物回填'},
    {id:'work',chapter:operate,title:'执行完成，交付事件立即补充看板',user:'按现有授权执行，完成验收后把产物和发布记录补上。',reply:'演示执行职能完成候选视频、验收与发布记录；任务完成事件立即更新交付区，数据职能接棒。此时粉丝结果还没有新读数，不能用交付完成代替涨粉。',caption:'第一类实时回填来自执行事件：先补交付，业务结果仍等待采集。',view:'work',checkpoint:'delivered',day:1,duration:8000,revision:2,action:'让数据职能回填观测'},
    {id:'collect',chapter:operate,title:'新数据到达，指标与趋势随事件更新',user:'通过连接读取当前数据，把实际变化补进看板。',reply:'数据职能核对后追加 11 月 12 日快照：粉丝 334，较昨日增 6。新视频只有 3 小时观察龄，单视频结果仍待成熟。新观测事件更新卡片和明细，复盘职能接棒。',caption:'第二类实时回填来自真实观测：按日期追加，保留更新时间和缺项。',view:'handoff',checkpoint:'observed',day:1,duration:8000,revision:2,action:'交给复盘职能分析'},
    {id:'first-review',chapter:operate,title:'复盘职能区分事实、假设与缺项',user:'今天做得怎么样？哪些已知，哪些还不能判断？',reply:'交付已验收，账号净增 6，但新视频未满 24 小时。不能因此认定短开场有效。建议先补齐同龄观测，保持主题和风格，继续小步验证。',caption:'干活之后先反思证据是否足够，再决定下一轮怎么干。',view:'review',checkpoint:'reviewed',day:1,duration:8000,revision:2,action:'把复盘接到下一天'},
    {id:'carry',chapter:operate,title:'主责把复盘转成下一天的具体计划',user:'保留这个判断，明天继续补数据和单变量尝试。',reply:'主责采用当前有效 Review，形成 11 月 13 日计划。任务保留上一轮数据和判断来源，已完成的产物不重复派发；长期 KR 保持原约定。',caption:'闭环不是停在一份总结上，复盘必须成为下一天的行动。',view:'next',checkpoint:'next',day:1,duration:7000,revision:2,action:'回放第二轮继续执行'},
    {id:'second-work',chapter:operate,title:'第二轮从上次学习继续工作',user:'按昨天的计划继续，不用我再解释一遍目标。',reply:'主责带着上次复盘派发新一日任务，执行职能继续准备单变量样片，交付区随验收更新。账号与视频数据仍显示各自最后有效观测，等待新数据。',caption:'再干一次：目标、项目、实验与上一次复盘保持连续。',view:'work',checkpoint:'delivered',day:2,duration:7000,revision:2,action:'看第二轮采集与复盘'},
    {id:'second-review',chapter:operate,title:'第二轮数据反馈，继续保留涨跌事实',user:'第二天的数据回来后，重新分析，再让我做选择。',reply:'回放新观测：粉丝 332，日减 2，周期净增 4。两条 T+24h 样片完播为 24% 和 32%，没有随机分流，仍只作探索性比较。复盘建议继续验证，不贸然全面换风格。',caption:'数据、反思再回来，人看到长期进展与短期信号后再做决策。',view:'review',checkpoint:'reviewed',day:2,duration:8000,revision:2,action:'查看我的决策点'},
    {id:'decision',chapter:operate,title:'人根据当前看板决定继续还是暂停',user:'我现在能基于哪些事实做决定？可以先暂停自动执行吗？',reply:'你能看到周期净增、当天负增长、样片观察龄、交付和解释依据。可以继续单变量验证，也可以暂停后续自动执行；暂停保留目标、看板与历史，不抹掉已经发生的结果。',caption:'智能体持续运转，人保留有依据的选择和控制。',view:'decision',checkpoint:'reviewed',day:2,duration:9000,revision:2,action:'继续单变量验证'},
    {id:'next',chapter:operate,title:'继续干活，形成下一轮',user:'继续小步验证，把今天的决定接到下一轮。',reply:'主责把决定和 Review 写入下一轮计划；执行、取数、回填和复盘继续接力。长期 KR、短期实验与每日行动都能相互追溯。',caption:'聊目标、拆结果、建看板，再进入执行与学习的持续循环。',view:'next',checkpoint:'next',day:2,duration:7000,revision:2},
  ],
  repo:[
    {id:'goal',chapter:talk,title:'先聊 repo 要解决的问题',user:'我想做一个 repo，实现基本功能后持续维护，也改善应用性能。',reply:'先明确它为谁解决什么问题、准备推进多久，以及你关心的结果。暂时不用先整理 issue 或建好所有工作目录。',caption:'从产品方向开始聊 OKR，而不是从优化结果倒叙。',view:'intent',duration:9000,revision:1,action:'说明周期与结果期待'},
    {id:'clarify',chapter:talk,title:'确认目标、周期和约束',user:'做 PocketBoard，用八周做到日常可用，发布版 API p95 不高于 300ms，每天留一小时评审。',reply:'O 是可日常使用、响应快且可持续维护。八周、300ms 与每天一小时来自你的要求；基准环境、起点和发布状态稍后核对。',caption:'先达成目标约定，再让智能体负责拆解。',view:'intent',intentConfirmed:true,duration:9000,revision:1,action:'请智能体拆 KR'},
    {id:'kr-proposal',chapter:split,title:'拆出功能、性能与维护结果',user:'基于刚才的约定，拆出长短 KR 和阶段检查点。',reply:'我提出功能交付、发布版性能和维护能力三类结果，分别用阶段、数值和清单呈现。候选优化是短期验证，发布后的性能才记长期结果。',caption:'不同 KR 用不同方式证明，不强行变成一个百分比。',view:'goals',duration:9000,revision:1,action:'整理对应的关键看板'},
    {id:'metrics',chapter:split,title:'分析指标和验收看板',user:'功能按核心旅程验收，性能只看固定负载下的发布版本。',reply:'生成发布版性能卡和趋势、功能阶段验收、维护清单。候选基准与发布观测有不同身份，不能混到同一结果里。',caption:'先说明 KR 对应哪些看板，再进入连接和建设。',view:'metrics',duration:9000,revision:1,action:'确认指标并寻找来源'},
    {id:'discover',chapter:build,title:'发现监控与基准来源',user:'指标确认。找发布监控和报告，能从浏览器读取就先读。',reply:'先核对项目、环境、版本和负载，再形成读取映射。缺少访问能力或字段时，保持待接入，不因填了网址就算连接成功。',caption:'把数据来源真正接上，生成过程才能变成可运行的看板。',view:'source',duration:9000,revision:1,action:'回放监控取样'},
    {id:'sample',chapter:build,title:'验证发布环境的样本',user:'按已授权的发布环境取一份样本，核对口径。',reply:'回放样本为 demo-v0.4，固定负载下 p95 720ms。它进入发布版序列，候选环境另行记录。',caption:'一条带版本和环境的事实，成为看板起点。',view:'source',sampled:true,duration:9000,revision:1,action:'生成整体看板'},
    {id:'board',chapter:build,title:'看板建成，旧历史不凭空补齐',user:'生成看板，保留已核对的观测与尚未验收的功能项。',reply:'演示看板保存发布版 720ms 样本、目标 300ms 和功能/维护验收区。没有读取的日期不生成曲线；任务完成和发布结果分别显示。',caption:'把看板建起来，是这一条故事线的明确出口。',view:'board',sampled:true,duration:10000,revision:1,action:'约定更新和复验'},
    {id:'schedule',chapter:build,title:'约定事件更新与发布后复验',user:'任务验收就更新交付区，发布监控有新结果就回填，发布后再复验。',reply:'交付事件更新候选区，监控观测更新发布区，复盘引用当前证据。页面显示各自实际更新时间，不用一个“完成”状态覆盖全流程。',caption:'看板随事件和观测更新，而不只是每天看一次结果。',view:'board',sampled:true,duration:9000,revision:1,action:'关联项目与职能'},
    {id:'projects',chapter:build,title:'使用现有项目，组织任务职能',user:'用现有 PocketBoard，不要给每条 KR 新建仓库。',reply:'关联稳定 project，写任务使用独立 worktree。主责排计划，执行职能做实现与验证，数据职能读发布监控，复盘职能分析线上结果。',caption:'明确执行载体与职责，再开始工作。',view:'projects',duration:9000,revision:1,action:'启动维护 Swarm'},
    {id:'activate',chapter:operate,title:'发布搭建方案，进入运行态',user:'按这版目标、看板与项目启动持续维护的 Swarm。',reply:'演示 Swarm 持续保留 KR、项目、成员与任务，执行、取数、复盘和调整按依赖接力。进入运行工作台查看任务与线上结果，跨天无需重新组建。',caption:'发布配置后，主要界面从对话搭建切换为 Swarm 运行工作台。',view:'launch',checkpoint:'assigned',day:1,duration:9000,revision:1,action:'安排今天的优化任务'},
    {id:'assign',chapter:operate,title:'主责派发可验证的优化动作',user:'先定位查询瓶颈，只改一项索引，跑固定负载和回归。',reply:'任务带项目、KR、基准环境与验收条件。执行者交付候选 PR 和报告；数据职能等待发布观测，复盘不会只听执行者说“优化完成”。',caption:'分工落到输入、产物和接棒条件上。',view:'handoff',checkpoint:'assigned',day:1,duration:8000,revision:1,action:'回放执行与交付回填'},
    {id:'work',chapter:operate,title:'PR 验收事件先更新候选区',user:'完成候选修改和回归后，把 PR 与报告补到看板。',reply:'回放候选基准为 280ms，PR 与测试证据登板；发布区仍保留最后的 720ms。执行完成事件不提前改线上 KR。',caption:'干完活就补交付区，但不伪造线上效果。',view:'work',checkpoint:'delivered',day:1,duration:8000,revision:1,action:'读取发布版结果'},
    {id:'collect',chapter:operate,title:'发布数据更新自己的区域',user:'再读发布版表现，不要把候选基准填成发布结果。',reply:'数据职能回填发布环境：仍为 720ms。观测到达事件更新发布区和时间戳；复盘职能据此分析候选与线上差距。',caption:'数据回填按来源和版本发生，不由执行者的自评代替。',view:'handoff',checkpoint:'observed',day:1,duration:8000,revision:1,action:'交给复盘职能'},
    {id:'first-review',chapter:operate,title:'基于线上事实复盘',user:'今天做得怎样，明天最值得推进什么？',reply:'候选值得继续推进，但长期 KR 尚未达标。下一步是评审、回归、获授权发布，再独立复验发布版；不能把 280ms 候选报告当成线上证明。',caption:'反思产生具体下一步，不停在“今天完成了优化”。',view:'review',checkpoint:'reviewed',day:1,duration:8000,revision:1,action:'查看我的决策点'},
    {id:'decision',chapter:operate,title:'人根据证据决定下一步',user:'可以先推进评审，也可以暂停自动执行吗？',reply:'可以。看板区分候选交付和线上结果，你可以继续评审与验证，或暂停新动作。发布授权和线上复验仍是独立的状态。',caption:'人看得到事实和差距，也控制后续动作。',view:'decision',checkpoint:'reviewed',day:1,duration:9000,revision:1,action:'继续评审与验证'},
    {id:'next',chapter:operate,title:'下一天从有效复盘继续',user:'先继续评审和回归，把这个判断接到下一天。',reply:'主责生成关联 Review、PR 和环境的次日计划。已有交付不重复派发，发布版指标继续等待实际复验；新结果再进入下一轮复盘。',caption:'目标、项目、执行事件、数据和人的决定持续连接。',view:'next',checkpoint:'next',day:1,duration:7000,revision:1},
  ],
}
export function sceneOffsets(kind: CycleKind): number[] { let total = 0;return dialogueScenes[kind].map(scene => { const start = total;total += scene.duration;return start }) }
export function sceneAt(kind: CycleKind, time: number): number { const offsets = sceneOffsets(kind);return Math.max(0,offsets.findLastIndex(offset => offset <= time)) }
export function storyDuration(kind: CycleKind): number { return dialogueScenes[kind].reduce((sum,scene) => sum+scene.duration,0) }
export function scenePlan(kind: CycleKind, revision: number): GeneratedPlan { return kind === 'repo' ? repoReplay : revision === 1 ? growthReplay : qualityReplay }
export function sceneCycle(kind: CycleKind, day: 1|2 = 1): CycleState {
  let state = initialCycle(kind)
  state = { ...state,linkedProjects:cycleDefinitions[kind].projects.map(project => project.id) }
  for (const action of cycleDefinitions[kind].actions) state = deliverAction(state,kind,action.id)
  state = reviewCycle(collectCycleData(state,kind),kind)
  state = applyNextPlan(state)
  if (day === 2) {
    state = { ...state,activeDate:'2026-11-13' }
    for (const action of cycleDefinitions[kind].actions) state = deliverAction(state,kind,action.id)
    state = reviewCycle(collectCycleData(state,kind),kind)
    state = applyNextPlan(state)
  }
  return state
}

export function sceneSnapshot(kind: CycleKind, scene: DialogueScene): CycleState {
  let state = initialCycle(kind)
  if (scene.day === 2) {
    state = sceneCycle(kind,1)
    state = { ...state,activeDate:'2026-11-13' }
  }
  if (scene.view === 'projects' || scene.checkpoint) state = { ...state,linkedProjects:cycleDefinitions[kind].projects.map(project => project.id) }
  if (scene.checkpoint && scene.checkpoint !== 'assigned') for (const action of cycleActions(state,kind)) state = deliverAction(state,kind,action.id)
  if (scene.checkpoint && ['observed','reviewed','next'].includes(scene.checkpoint)) state = collectCycleData(state,kind)
  if (scene.checkpoint && ['reviewed','next'].includes(scene.checkpoint)) state = reviewCycle(state,kind)
  if (scene.checkpoint === 'next') state = applyNextPlan(state)
  return state
}

export function sceneLifecycle(scene: DialogueScene): 'building'|'running' { return scene.checkpoint ? 'running' : 'building' }
