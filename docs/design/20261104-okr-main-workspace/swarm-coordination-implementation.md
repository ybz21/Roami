# 原 Main 的受限自动协调：实施记录

关联 #744，沿用[通信逐跳HTML](communication-engine.html)、[协调契约](swarm-delivery-contract.md)及[持久收件箱](swarm-inbox-implementation.md)。仍以原宣传团队的真实交接和每日循环为最终验收；本记录不把授权层专项当成整个机制已完成。

## 用户故事与入口

用户继续在本 OKR 的原 Main 聊目标，由 Main 指挥原 X、B站和数据成员。开启长期协调需要实际用户在原 Main 当前回合给出的目标引用，明确选择已有稳定成员ID；不重建负责人、不按角色名创建替代实例、不自动启用历史成员。以后成员问题只是待处理数据，不能变成新的用户同意。

定时输入引用已存在的目标委托，不再将一个定时字符串当成新授权。用户暂停团队时停止新协调，保留问题和历史；用户撤销委托时保留原记录与真实撤销消息来源。

## 已开始的授权层

基础层已随 PR #754 合入，尚未注册公开目标工具或启用调度。schema25迁移定义新增空的 `swarm_goal_delegations`、`swarm_coordination_batches` 和 `swarm_coordination_inputs`；不猜测或自动激活已有团队的委托。代码合入不代表生产已迁移。

- `dispatch/swarm_delegations.py` 在同一事务检查原项目Main、当前实际user turn、原上下文准入、目标quote与明确的同群成员，并保存委托/请求回执。当前回合的停止、遗忘和错误身份不能获得委托。
- `storage/swarm_delegations.py` 复用 canonical project Main 及实际群绑定，不新增另一份Main注册表。来源是未删除/未遗忘的实际用户消息，带scheduled的user记录也不合格；保存引用和内容摘要，成员文本不能填权限字段。
- 保存实际模型上下文中的用户来源引用，供撤回检查；后续使用允许原用户回合已结束，但必须仍位于当前分支可见历史。真实分支fork保留或排除目标时有不同结果，不能只检查conversation相同。
- 后续续派还必须验证原成员的当前task/revision/run、会话关闭、stop/unknown及workspace。本层不提供绕过这些保护的入口；普通completion不可续派的原保护保留。

## 已开始的批次存储

`storage/swarm_coordination.py` 只供宿主接线，当前没有外部入口或Scheduler扫描。`enqueue` 在同一writer事务复核真实目标和原Main空闲状态，选择明确授权的原成员当前run的待处理消息，冻结其正文与来源，并原子写入batch、continuation turn、turn.run job及事件。不会新建user消息、用户授权、团队或实例。

每个inbox条目最多绑定一个批次。读取和冻结都不改变read/handled回执；处理失败不无限重唤醒，后续显式恢复必须复用原批次和输入。晚到消息不改变旧批次，下一批只取未冻结的新条目。等待用户、已有排队/运行回合或进度消息都不会启动新批次。原Main的自发消息不会通知自己。

`admitted_batch` 校验宿主batch/turn/job绑定、原Main当前分支和活跃目标，以及持久stop/遗忘保护；实际工具动作须传当前lease epoch，防恢复后的旧执行器继续写。`TurnMailbox` 已在领取时复核：有其他真实用户回合或正在等用户时推迟同一job；暂停保留队列，授权撤销或无效来源则停止该回合，保留问题与批次。后续Scheduler仍需接事件、恢复及日程入口。

私有真实备份副本从schema22升级25，60张原表的原字段/行哈希一致，原Main保留，外键检查为零；五张新增表均为空，没有替旧团队创建授权或自动协调批次。未写线上库。

`TurnJournal.origin` 已识别实际continuation回合的宿主批次。只有batch/turn/job匹配、当前lease与真实目标仍有效时，才返回原用户消息ID及委托quote；缺少ledger或伪造job批次ID在Mailbox或Journal拒绝，成员或导入的user正文不能代替授权。

## 模型上下文与工具范围

`context/swarm_coordination.py` 与 `PromptBuilder` 分别投影原用户目标、稳定成员和冻结输入，记录原用户sourceMessageIds及batch证据；不把成员正文再插成user消息。重建上下文仍读取原冻结输入，晚到内容不混入；Core在新用户优先后恢复同一批次时使用system恢复记录，而非制造新的user请求。`context_admission` 在协调回合的流式写入前也复核当前委托，撤销后不能继续吐迟到正文。

`Tools.invoke` 在CLI/基础工具完成解析后调用 `SwarmCoordinationPolicy`，CLI实际上下文带当前lease。范围取自宿主ledger，不信调用者的项目、workspace、任务或权限标记：

- 只读原群、已选稳定成员及其当前原任务；回复只能引用本批真实post，回给原作者；宿主按batch/post生成回复业务键，跨新tool call重试仍去重。普通进展或定向问题须提供稳定业务键。
- 文本产物通过已有run证据查询限定到已选原任务的当前run；`read artifact://` 不能绕过范围。独立验收仍走原 `swarm_verify` 及其完整读取要求，不凭答复改任务成功。
- `TargetDirectory.project_workspace` 从实际Go项目show取得同一注册项目绝对目录；文件读取覆盖调用夹带的workspace，仍走既有无符号链接穿越文件I/O。读取返回前复核来源及项目目录，目录变动/委托撤销时不返回旧字节。
- 新建角色/团队、任意shell/session、跨项目任务和配置改写拒绝。项目写入先限已存在的record/review及共享记忆CAS；通用文件写入不开放。`task_steer` 只在同回合先取得当前task/revision/latest run的成功状态回执后开放；宿主填入revision、原目标来源、当前lease以及batch/task稳定业务键。一次批次对同一原任务只接受一个有界指令，换tool call或调用key不能重复续派；不同正文返回键冲突。不会借普通Main权限扩大协调范围。

早期127项集成专项另包含Core处理宿主批次的17项工具专项：原Main答复后回合正常结束，原成员取得关联回复，不新增user消息/实例/任务，不代替任务验收。普通Main、基础工具、目标发现与原completion回归也在覆盖范围。随后完成的真实Go私有上下文/roami chrome链路及完整门禁见文末；仍未计生产模型或原宣传团队的自动协调通过。

`PromptManifests.record` 已在同一事务校验真实宿主批次/当前lease/有效委托与上下文中的batch证据，持久保存coordinationEvidence，并为实际投影的冻结inbox条目记录一次read回执。只冻结、构建候选prompt及人类预览都不写已读；晚到消息保留未读，不修改handled或任务验收。撤销、错误lease、证据不匹配或manifest插入失败均不留下已读/事件副作用。这里的已读表示已装入该轮实际模型请求上下文，不表示模型理解或任务完成。

## 原任务续派接线

### 原目标与实例保持

协调请求传入真实source turn与lease，宿主从ledger取得delegation、原用户message/quote、原稳定成员、当前task/revision/run及原Main分支；这些字段不接受模型权限标记。Main的具体assignment单独存储，原目标及其限制作为授权上下文保留，不把成员问题写成用户同意。命令重试和任务轮次沿用既有TaskRevisions回执。

授权引用随task.steer job和新revision的intent保存。等待停止证明后、准备新run及提交真实执行前，重新检查当前委托、原Main分支、原成员/task、会话关闭与原用户来源。Main正常结束回合不使已接受的续派失效；持久stop、遗忘、撤销、范围/目录变化则阻止迟到启动。没有实际提交时保留明确未开始的结果，不假装unknown或成功。后续真实用户手动续派提供新来源，不继承已撤销的自动协调标记。

目录取宿主的注册项目show结果，并比对原任务已保存的workdir/workspace；原session任务可能没有projectId，不能据此重建或猜session。当前原宣传三名成员均保存同一项目根目录，原task/provider/workspace继续保留。无法证明属于原项目的其他工作区应明确拒绝并保留原件，不能默默改目录。准备中目录与授权需再次检查；不能只在最初工具预检时检查。

| 模块 | 必须落实的行为 |
| --- | --- |
| 协调批次存储 | 基础存储已开始，继续接入启动恢复；失败后不另造身份、不吞掉未答复消息 |
| Scheduler / TurnMailbox | Mailbox已接；继续接事件与日程产生批次、真实启动恢复、等用户及暂停恢复；Main自己的回复不自唤醒 |
| TurnJournal / PromptBuilder | 来源、冻结投影与恢复已接；继续核验完整manifest、reply来源审核、真实CLI/browser及原团队链路 |
| ToolGateway | 已解析操作的范围检查已接；继续绑定受管续派、结果桥接与完整事实/文件发布验收 |
| TaskRevisions / TaskDispatcher | 已接线：Main有界指令与原用户目标分别保存；等待stop证明、异步目录查询后及真正执行前复核；暂停恢复保留同一操作/run |
| 结果桥接 | 与现有task.completion去重身份共用处理；已运行的旧completion不改输入，历史无委托记录不擅自获得协调能力 |
| 问题与回执 | 读取不消除待处理；实际同群reply、受管steer或明确未解决决定才形成处理凭据；任务验收继续独立 |

handoff与完成回报须区分“同一个run的结果”和“新补充业务消息”。重复结果通知不启动第二次Main，新的问题/证据使用新业务身份；已经冻结或处理的批次不能冒充读过晚到正文，也不能因旧结果成功而吞掉未读内容。结果、message read、handled与任务验收四种事实各自留凭据。

项目文件/产物读取属于隔离边界，已从宿主项目show绑定目录及同群产物范围，不采信成员提供的任意路径、session或权限标记。

### 原生执行与暂停恢复

新revision沿用原任务、原native branch或CLI provider/session，不新建角色、任务或对话。TaskRevisions在原Main正常结束后仍可处理已接受的有界指令，但撤销、持久stop、遗忘、会话关闭或目录变化会阻止迟到执行。新增授权跟随原task.steer回执保存；新的真实用户手动续派移除旧自动授权。

NativeExecutor在workspace返回后、绑定事务内及进入真实Core前复核；目录变化使绑定事务回滚，保留原workdir。准备期间暂停则将同一run/job恢复为待执行，结束尚未开始的准备turn；恢复仍使用原native branch，workspace_prepared业务事件按run幂等，不能因重复事件键使原轮次失败。

本轮native-retrieval-target专项 **89 passed in 38.29s**（含委托、冻结上下文/已读、工具范围、原生工作区既有回归和续派）：受控模型走实际Core，验证正常续派、prepare前撤销/暂停、已绑定后暂停并恢复同run，以及返回目录变化回滚；旧attempt证据和原实体保留。此前retrieval-target2为69项，属于重叠验证，不能相加。尚非生产原团队或真实Go CLI/socket验收。

失败/撤销后的显式恢复仍未实现：不可删除input记录、换key重造批次或静默改旧委托。新目标/新委托也不能直接重放旧失败批次。恢复须保留原batch/turn/input及既有写回执，并追加真实用户来源的恢复授权；重新检查旧来源未被遗忘、原成员/run与当前范围。来源已遗忘则保留未解决状态，不能借新委托重新暴露旧内容。这一恢复契约与handoff/completion去重完成前不开放自动调度。

## 交付边界

本基础层已通过完整门禁、正常提交钩子及CI，并在PR #754合入。Go备份兼容、旧库副本迁移和真实Core/CLI/浏览器隔离链路已验证；没有生产部署或原宣传团队自动协调的运行证据。继续按[显式恢复设计](coordination-recovery.md)补齐恢复、结果桥接和生产者，再做原项目交接；#744保持开放。下面保留首次失败、业务键修正与最终验收的证据边界。

首次完整门禁在Skill package.files内容哈希校验停止（1 failed、2399 passed、28 skipped），原因是经验文档变更未同步资源清单。按仓库生成器刷新后，模板/Skill三项专项通过；本次失败日志保留，不计为full通过，随后重新运行完整门禁。

独立审查另复现两例：progress/question夹带宿主reply业务键时，后续真实答复冲突。现把普通消息放入独立message命名空间，答复仍使用宿主batch/post身份；普通消息之间仍共用身份域，重试改kind/recipient继续拒绝。新增三项回归，相关78项通过（30.47s）；最终真实Core→Go CLI→私有上下文22项再次通过，包含两项目刻意占用reply键的进展后真实答复、四份实际CLI回执；五档窗口无溢出，三个自有服务和端口/profile已清理。旧kind分域中间验证及启动夹具竞态日志保留，不当最终候选。

修复前full2通过：运行时3950 passed、48 skipped、6 subtests（1104.75s），Go全量及四类Skill检查、前端门禁/build通过。此结果仅对应修复前源码，最新消息键守卫另跑full3，未沿用旧绿灯。

## 本轮隔离验收

实际Go CLI成员提问、宿主显式冻结批次、真实Core调用Go CLI再经过私有active-tool上下文返回Python原handler，原成员CLI读到关联回复；roami chrome操作原组件验证两个同名项目隔离，共22项断言。真实manifest保留batch来源、原用户和冻结inbox身份；没有新用户请求、实例、任务或成员。1280/1920/2560/3440与390模拟视口无document溢出，手机未操作，不记真机通过。

模型受控、Go项目API/auth为测试门面，batch由测试宿主明确排队，不声称生产Scheduler自动唤醒。两项目进展和回复共四份实际Go CLI私有调用回执。三个自有服务已退出、三端口关闭、profile移除，私有tmux仅经同一isolated入口停止，报告/数据库保留。

本轮full：3953 passed, 48 skipped, 6 subtests passed in 1064.56s (0:17:44)；Go全量、ruff check/format、前端typecheck/i18n/hover/build及统一门禁通过。前端产品源码未变化，未另跑Vitest或触手机。随后正常commit quick完整运行，记录见交付日志。自动调度/公开目标工具、显式失败恢复和结果桥接仍未开放，#744保持开放，不把本基础层验收当成线上每日循环。
