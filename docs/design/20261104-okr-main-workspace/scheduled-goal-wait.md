# 按已登记日程等待原 Main

关联 #841、#826。[可交互机制原型](scheduled-goal-wait.html)。

设计与本地实现候选，尚未部署。不改变现有发布窗口，不触手机或账号页，不创建新团队。原项目每天09:00的既有插件日程保持。

## Product Design

持续目标既要能自动接着做，也要能在本日工作完成后等待真实的下一次排期。Main 不能仅写“明天再做”就退出，也不能为了通过接续门禁反复派索引、哈希和相同预检。界面只显示一句“明天09:00继续”，详细日程与核验记录按需查看。

当前证据：production69 的 GoalContinuation.prepare / active_next_steps 只承认原任务执行、待运行/续派job，或有实际失败工具的blocker；没有已登记排期的分支。原插件实际 cron.list 已确认 morning enabled、Asia/Shanghai、nextRunAt=2026-11-10 09:00、指向原project/Main/Swarm/delegation。仅这份设计不声称生产Main已经因此空转；后续用实际协调回合或真实fixture验证。

## User Stories

- 本日审核、投稿、取数、复盘完成，Main检查既有日程后等待下一次09:00；原实例与记忆保留。
- 成员尚有待验收/结果未知时，不能用未来日程掩盖这些事项。Main先交代并处理当前交付。
- 日程关闭、目标撤销、项目变更或执行器不可用时显示真实状态；日程登记不等于已唤醒。
- 到期使用现有daily slot唤醒原Main；重复tick仍按同一日期/slot去重，不新增第二条计划。

## Technical Design

1. 增加有范围的只读schedule evidence适配器，查询安装节点的原cron插件。使用真实限定命令 `roami plugin run roam.cron:list`；不把所有插件命令开放给Main，不执行cron.run/tick/add。
2. 从宿主绑定project/Main/Swarm/delegation查项目已确认的日程声明，读取所指唯一job。完整解析已登记exec参数，精确核对原wake_main.py路径、project、conversation、swarm、delegation、timezone、slot，拒绝同名但指向其他项目或多义/混合命令。只读验证实际runner健康，单有enabled配置不能声称未来必然执行；不采纳模型自报nextRunAt或本地receipt文件。
3. 返回最小证据：原身份、插件/job、时区、nextDue、实际observedAt与runner状态。隐藏其他项目job命令和账号资料。失效、停用、过去时间和无法验证状态均不产生有效等待。
4. Main显式选择等待已登记排期，绑定当前批次、目标revision/source/lease和实际证据。等待不创建计划、不完成目标、不批准发布。宿主在回复收口前复核，并在原命令账本保存scheduled_wait checkpoint；没有排期证据仍走原NEXT_STEP_REQUIRED恢复。
5. 继续保留已有任务执行/续派与明确失败blocker；同一批次只保存一个真实决定。到期仍由当前cron+daily去重通知处理，不引入并行计时器。配置变更/关闭后的恢复必须在同一源日程上对账；不能无条件创建新的唤醒。
6. 缺少健康可读能力时，明确保持该等待分支未启用。生产日程继续原样运行，不能通过伪造失败或制造无用成员任务来绕过门禁。

### 模块边界

- executors/project_goal_schedule.py：只读节点CLI/runner适配，明确失败语义。
- dispatch/swarm_goal_continuation.py 与 storage/swarm_goal_checkpoint.py：当前身份、排期证据与不可变决定。
- Main目录/协调目录/Foundation注册命令：只暴露当前项目的读取与选择等待，精简返回值。
- 原cron/daily：保留单次日槽去重、暂停/撤销/忙碌后恢复语义；不改账号或发布通道。
- 通用OKR Skill与真实项目手册：说明何时接续、何时等待、怎么核对真实nextDue与运行回执。

## Acceptance

- 隔离实际运行时fixture：有正确的启用未来日程且runner健康时可等待；配置文件自报日期不能通过。
- 拒绝其他project/Main/Swarm/delegation/时区/slot、相同名字不同命令、禁用插件、runner停用、过期时间、旧lease、目标撤销/遗忘、暂停、重复/改变请求。
- 有未处理交付或未知发布时不能用计划等待冒充已经收口；等待本身零发帖、零新任务、零新增日程。
- 自然到期原Main获得唯一daily notification，接原成员任务；原Chrome/ADB发布、Connector、实际看板、记忆与下一步分别验收。
- 用roami chrome检验群聊/Main对话的运行状态与一句排期说明；原项目真实未来窗口到期前不记自然唤醒通过。

## 原型验证（2026-11-09）

使用独立 QA Chrome 页实际点击，六种场景及重复模拟到期均通过；JavaScript解析通过。原型不连接生产、不创建计划或任务，也不证明实际到期唤醒。验证记录 `/tmp/okr-scheduled-wait-design-20261109/prototype-checks.json`。

## 本地实现候选

`executors/project_goal_schedule.py` 只读原项目日程、限定归属的 cron:list 和当前注册项目；固定模板唤醒脚本与 builtin Skill 摘要相符，显式绝对 PATH 必须解析到节点既有 roami，字面命令由 shlex.join 构造。项目/Main/Swarm/goal、时区和日槽逐项匹配，下一次时间必须是真实未来日槽。

`executors/systemd_cron_runner.py` 通过 busctl 的类型化 systemd D-Bus 属性核验活动的每分钟 timer、它的实际 service 和有效 ExecStart；不解析 systemctl 人读日志，不启动/启用服务，拒绝全局 tick 或其他 job。当前支持既有 Linux 单日槽 exec；其他运行器保持明确不可用，不自动迁移计划。

`dispatch/swarm_goal_schedule.py` 与 `storage/swarm_goal_schedule.py` 只保存显式等待：当前原任务均成功、无未知结果/待续派，当前问题与交接均已答复。等待绑定原批次/目标版本/来源摘要/lease和原任务身份。现场探测后、最终回复前及最终完成事务再次核验；变更、过期、撤销、暂停与遗忘都不能复用旧决定。重试保留原账本身份，不产生新 job、任务或实例。

Main 注册目录新增 `swarm_goal_wait`，Foundation 为 `roami swarm goal wait --input JSON`，只接收 swarmId/reason。原接续门禁允许已核验排期等待，继续保留真实执行与具体阻塞路径；用户输入不能提供时间、路径、job或证明。

已完成107项隔离回归（含目录/协调/接续及完整Skill包），另通过真实节点只读探测原09:00计划、原唤醒脚本与实际systemd runner；证据 `/tmp/okr-scheduled-wait-design-20261109/{final-targeted-tests.log,actual-node-readonly-proof.json}`。这些结果不代表生产工具已注册、Main已选择等待或未来日槽已执行；完整门禁与线上验收仍待完成。

## 2026-11-10 实际遗漏与修订

原09:00日槽已实际发布B站三稿、登记15稿并确认rev66；原Main随后在X三条仍未发布时选择等待11-11。等待理由把此前仅限维护回合的“不派工”扩为后续限制。原任务全成功仅说明已派工作结束，不说明今天的下一阶段完成。

修订沿用独立目标接续审核，不新增定时器或发布通道：审核输入包含当前宿主核验的排期等待提案、真实用户来源、原目标与原任务。等待提案仅是模型主张，不是完成或新授权。独立审核区分“今天仍欠有界工作”和“今日已收口、下一次真实日槽继续”；前者返回NEXT_STEP_REQUIRED，原Main在同回合恢复，后者仍须原日程与身份复核。单回合维护限制不永久取消持续目标，明确的持续暂停/设备限制仍有效。缓存摘要绑定完整提案；无提案时保留原持续目标判断，不能复用提案前的结论。

验收须覆盖：全部task成功但仍有未派发当日事项时拒绝等待；当日实际完成允许等待且不称目标完成；提案变化重审；审核期间真实任务/来源变化拒绝；既有未知/未验收/过期日程继续拒绝。线上X接续和完整循环另行实测，不由此设计或测试替代。
