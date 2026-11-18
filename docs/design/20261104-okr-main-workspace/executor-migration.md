# 同一职责的执行器迁移

2026-11-18，用户要求宣传项目的 Main 和现有当前团队全部改为 Claude Code，模型使用已配置的 free 池。整个项目仍暂停，不恢复发布、评论或日程。该要求覆盖项目旧指引中不允许改变执行器/模型的历史限制，但不授权修改其他项目或全局模型路由。

## 身份与历史

Main 的多执行器适配与成员的执行代际分开实施，最终均须满足要求；项目 defaultAgent=claude 只影响默认选择，不等于迁移当前 Main 或成员。

原职责、成员ID、记忆目录、历史任务、attempt、原 provider 对话与平台证据必须保留。跨执行器不能声称原生上下文相同；切换通过可读交接、项目文件和持久记忆接续。历史淘汰成员不是新增当前团队，不因本次迁移重新启动。

## 成员迁移第一批实现

新增 `roami swarm migrate SWARM_ID --file request.json`；宿主 POST `/agent/swarms/:sid/execution-migrations`，需 owner、commandKey、expectedRevision 和明确 memberId/executor/model。例：

```json
{"commandKey":"switch-1","expectedRevision":43,"members":[{"memberId":"实际原成员ID","executor":"claude","model":"free"}]}
```

命令必须在 Swarm 暂停、Main 无运行/排队回合、成员及子任务终止、任务队列无待执行工作、最后attempt有 inputStopped/outcomeKnown 证明、资源租约已释放时才能生效。结果未知不能借迁移清 busy 或删旧任务。全批事务执行，一个成员不满足条件就回滚全部；同键相同请求返回同回执，异请求拒绝。

迁移保留旧 task/attempt/对话与 member_rounds；同一 work 进入“等待重新分配”，递增 execution_generation，保存新 executor/model。不会立即派工、恢复团队或复制旧发布请求。Main 后续显式 plan 同一 memberId，才能更新新一代限定任务；新task使用带代际的幂等键，避免误命中旧执行器任务。后续轮次仍续派这个新task，不每轮新建实例。

原生 Roami 成员旧会话留在历史，不再投影成当前 Claude 实例。角色列表和CLI JSON公开成员选定模型。当前只支持切向 CLI 执行器，切回 native 的实例恢复协议另行实现并明确拒绝，不静默复活旧 native 会话。

数据库schema30新增成员/工作项model与execution_generation；Go备份兼容上限同步。实际升级需要标准离线备份和schema初始化，不能直接改生产SQL或强制跳过idle guard。

## 当前证据与未完成项

本机实际模型目录有 enabled/freeOnly 的 `free` 聚合池；项目默认Agent已设为claude并独立读回。既有Main、Swarm和当前团队仍保留，Swarm paused=true。旧Claude数据任务已通过保留的原停止证据前缀及后续仅有本地压缩的严格核验，正式记录为未执行新输入的失败；正常runtime观察后任务为interrupted，追踪hasUnknown=false。这个结论只覆盖执行状态，不改变任何平台发布事实。

隔离回归覆盖：暂停/修订要求、批量回滚、原职责与native历史保留、运行/取消/等用户与未知停止阻止迁移、显式重新分配、free模型传入新Claude任务、旧task字节不变、重复advance只产生一个新代际任务；CLI验证一次owner绑定请求且保留model字段，HTTP代理路由存在。整体full与最终PR记录另外补充。

尚未完成：Main自身CLI执行适配与可信切换；本批完整质量检查、PR/合入/标准升级；项目确认配置与运行绑定同步；把已就绪的四个成员及Main候选实例接回原身份。源码、候选实例或项目偏好变化不能当正式绑定已完成。目标继续保持active。


## 接回已就绪的实例

候选实例先通过 Go 的真实 Claude CLI 启动，固定 `model=free`、原项目目录和自动权限，仅执行禁止业务操作的初始化。`agent execution prepared --key` 核验原生 provider、tmux身份、宿主/目录证明、原模型配置、原初始化结果及实际空闲状态。只有生成者的真实结果和生命周期记录能给出这个证明；Python端不接收调用者自报的 ready 或停止标记。

同一迁移请求可增加 `preparedLaunchKey`：

```json
{"commandKey":"attach-prepared-1","expectedRevision":43,"members":[{"memberId":"实际原成员ID","executor":"claude","model":"free","preparedLaunchKey":"已就绪实例的真实启动键"}]}
```

`SwarmPlans.migrate_execution` 先核对原幂等回执，再使用 `TargetDirectory.project_workspace` 读取当前真实项目根目录，调用 Go `prepared` 进行只读核验。模型、执行器、原生身份、会话和项目目录任一不符都拒绝。等待Go返回后，在数据库事务中重新校验当前修订、暂停和停止条件；过期结果不能覆盖新的团队安排。重复请求返回原回执，不因实例已经进入后续回合而重新初始化。

schema31添加成员代际，以及 `swarm_member_provider_generations`。每代保存 memberId、generation、owner、swarm、启动键、物理会话、provider身份、执行器、模型、原生绑定与workspace。成员身份和个人记忆路径保持原样；旧代际行及旧任务不重写。同一物理会话/启动键只绑定一次，同一provider上下文不能给其他成员共用。触发器核对成员、项目Swarm、owner、当前代际、执行器和模型，避免绕过服务逻辑写出错属关系。

Main显式plan下一轮时，复制成员当前代际到原work。`advance`读取该代际的已绑定provider，把任务目标设为这个真实session，使用现有CLI续接协议，不能再建一个同名新会话。已有session的model不通过任务参数重设，而是继续使用初始化时已证明的free配置。未绑定候选实例的普通迁移仍采用新任务初始化流程。Swarm保持暂停时不会派工。

`snapshot.members[].provider` 和CLI JSON提供精简代际/会话/模型信息；新的预览/聊天入口还需在打开时重新核对原生身份，不能只凭这份静态投影绕过现有任务/会话边界。

### 本轮实际证据

- 原恢复路径修复已提交PR #954（`36e45098`），quick/full通过；额外可执行文件身份核验正在追加验证。
- 原schema30迁移切片full通过：5013 passed、48 skipped，前端构建与质量门通过。schema31接续扩展的整体full尚待完成。
- X维护、B站维护、评论运营、数据分析以及Main候选均已真实启动并经Go核验：Claude、free、ready=true。只做初始化，没有恢复运营、定时任务或Swarm。
- 当前生产Swarm仍revision43且paused；原成员执行器绑定及原Main未被这些候选自动替换。部署和实际迁移后须重新读取团队、项目定义、任务/原生身份，并验证原历史完整保留，才可报告切换完成。
