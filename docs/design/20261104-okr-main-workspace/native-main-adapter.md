# 项目 Main 接入原生执行器

状态：实现与隔离验证中，2026-11-18。当前用户再次明确要求 Claude 接管旧 Codex 并恢复工作；原暂停要求不再作为永久运行限制。迁移要先完成原成员绑定，再恢复明确的接管任务；发布结果未知的旧内容仍先对账。

## 产品与用户故事

项目 Main 在搭建态和运行态保留同一个逻辑身份。选择 Claude Code/free 后，用户仍从原项目 Main 聊天入口发需求，原 Main 继续指挥原团队，历史与记忆不迁到首页 Main。用户可查看 Claude 的实际工具过程与原生对话，界面复用现有 ClaudeChat/CodexChat 与 AgentViewToggle，不另造输入框。

当前四个成员及一个 Main 候选都已实际启动 Claude/free 并通过只读就绪核验；候选启动不是正式切换完成。成员的 provider generation 接续代码已经实现并在完整验证；Main 的首版运行适配已接线，尚待入口隔离与线上验证。

## 技术实现边界

1. 项目 Main 的配置绑定到原 project_okr_mains 的 owner/project/conversation，不创建另一个 Main conversation 或冒充团队成员。保存 executor/model/generation/prepared launch key 与原生绑定；宿主读取真实项目目录并通过 Go 验证，禁止绑定首页 Main、其他项目或错误 provider。
2. 按当前 turn 的原 Main 身份选择执行器，不能改变全局 model、路由、费用或其他项目。原生 Main 使用实际 Claude CLI 的 free 配置，不能用 Roami 的另一个模型代替 Claude 原生执行器。
3. 复用 AgentLoop 的原对话日志、排队、抢占、来源、最终交付和错误状态。原生 Model 适配器按 turn 创建，避免临时修改共享 loop.model 导致并发项目串线。若使用 loop 副本，必须共享原 turn_tasks/preemptible，取消时通过真实 Go 执行取消/停止核验，不能只取消 Python await。
4. Go 执行使用原 Main provider 的持久会话、原初始化键和当前 turn 的稳定幂等键。provider/model/PID/宿主等身份改变时拒绝续接，等待明确恢复；不能按展示名重新绑定。初始交接给原项目记忆、历史引用和近期 Main 上下文，保留原始历史入口。
5. 原生 Claude 自己执行实际工具；适配器不得把原生工具记录再次交给 Core 执行。最终正文必须来自实际原生结果；如 Core 要求 reply 工具，可用明确的交付桥接封装实际最终文本，不能伪造平台回执、工具成功或停止证明。
6. Main 入口复用现有 ClaudeChat 与 AgentViewToggle 显示实际工具和流式过程。原 Main CID 保留历史与事件身份；原生 provider ID 用于原生消息展示，二者不是随意互换的 conversation。群聊投递仍进原 Main 的排队入口，再由已绑定的执行器处理。
7. Swarm 成员的任务继续通过原 member/work 和真实 provider generation 调度。Main 自己的执行器不能伪装成新 worker task；成员报告、投递成功和独立验收仍分开处理。

## 模块与验收

预计模块：项目 Main generation 存储与服务、按 turn 选择的 CLI Main Model 适配器、Runtime 选择/抢占接线、宿主配置API，以及复用原生聊天的 Main 入口。Core 保持注入端口，不直接导入数据库、Web 或 CLI 实现。

必验：项目/首页隔离、两个项目并发不串模型与会话、原 Main/团队/历史ID不变、free模型实测工具调用、稳定会话多轮复用、原生工具流可见、取消未知不重发、用户新要求抢占、群聊进入同一个 Main、真实派工与回执闭环。候选实例的 Claude/free/ready、真实文件制作与宿主隔离测试分别作为各自证据；不能把它们当作线上 Main 运行接入验收。

## 首版实现

- `conversation/main_execution.py`：原项目 Main 的 provider generation 配置服务；认证 owner、原 Main CID、真实项目目录、Go prepared 证明、Main 空闲与 Swarm 暂停均须通过。命令回执按项目幂等，禁止把已绑定给其他项目或成员的 provider 复用为 Main。
- `migrations/0032_project_main_providers.sql`：保留原 `project_okr_mains` 身份，单独保存原生绑定与 generation；不改旧对话、任务或个人记忆。
- `providers/native_main.py`：每一轮注入原生模型端口，使用原 provider/session/初始化键；稳定 turn+context 幂等键经 Go 执行，原生工具只执行一次。只有实际成功并确认停止、结果已知的回执可交付正文。未知或失败不会包装成成功。取消必须调用 Go 并核验停止，否则不进入自动 defer/retry。
- `app.Runtime.run_turn`：浅复制当前 AgentLoop，只替换本轮 Main model；共享原 `turn_tasks` 和 `preemptible`，保留原队列、群聊入口、抢占、日志与 reply 交付链，不修改全局模型或其他项目。
- `server/main_execution_routes.py` 与 Go 代理：`GET/PUT /api/agent/conversations/:cid/execution`。PUT 接收 projectId、commandKey、expectedGeneration、executor、model、preparedLaunchKey；客户端不得提供自报 ready/stopped 的字段。

当前只允许从原 Roami Main 初次绑定已就绪原生 provider；再次更换已有原生 Main 明确拒绝，需后续补齐原 provider 的正式停止/退休协议，不能直接覆盖。默认执行器与首页 Main 不受此配置影响。

## 本轮隔离证据与待验

2026-11-18 的 23 项专项覆盖原 CID 不变、命令幂等、owner/project/provider 边界、配置 API、真实 Runtime 队列与 reply 链、群聊 @main 到同一个 provider，以及未知停止阻止自动重试。专项使用可控 Go 命令端口，证明宿主接线，不作为线上 Claude Main 验收。现有真实 Claude/free Read、X 草稿及 B站40秒视频制作是原生成员能力证据，不代替 Main 接入验收。

待完成：完整质量检查、PR/部署、原 Main 真正绑定与多轮派工验证、原生工具过程和原始会话的前端入口、现场全成员模型与回执审计。生产尚未升级 schema32。

### 正式绑定前的入口隔离

`ConversationService` 的 `/model`、`/status` 已按当前项目 Main execution binding 显示 Claude/free；绑定后的模型命令不写全局设置，其他模型拒绝并保留当前实例。原生 `/compact` 引导到原生终端。首页模型未配置也不阻断已经绑定的项目 Main。

`ExecutorSessionChat` 复用 `ClaudeChat`/`CodexChat`、`AgentViewToggle` 与原终端组件；Swarm 成员和项目 Main 使用同一组件。发送仍通过原 Main CID 的队列，不直接写终端绕过群聊与宿主。共用聊天组件支持命令处理端口：Main 的模型和停止按钮进入原宿主命令入口；仅原生可执行的压缩、推理参数等命令引导到原生终端，不把它们当普通任务提交。成员及首页未指定该端口时沿用现有原生行为。前端核对项目、CID、provider、generation 及共享 overview 中的真实活动会话，失配不回退首页。历史引用继续打开原宿主消息。草稿迁移不覆盖已有原生草稿，未知发送的请求键和原 OKR 上下文跨重挂载冻结保存。

### 暂停迁移与目录发现

生产只读审计发现原 X/数据任务已经终止且有真实停止证明，但 `swarm.coordinate` 通知在暂停期间反复排队。迁移不把该通知视为原生执行，保留通知及原始回执；`task.run`、`task.verify`、`task.steer`、`task.close_session` 等实际任务控制仍然阻止迁移。迁移后通知桥通过当前 work/task 关联复核，旧通知不能指向新 generation。

`roami project show ID --identity --json` 直接读取登记项目身份、目录、归档与默认执行器，不扫描全机 worktree/session，也不使用项目列表缓存。宿主的 5 秒目录发现使用此通道，避免把慢速全列表扫描误报为目录不可用；身份与绝对路径校验保持。

### 补充验证进度

本轮 scoped commands、原生 UI 和草稿恢复已有专项及前端全量验证；通知迁移专项 18 项、目录发现与迁移合计 36 项通过，Go 身份 API/CLI 专项通过。此前首版 full 为 5052 passed；本轮新增实现仍须最终 full、PR 更新与部署，不能沿用首版通过结论宣称已上线。手机未操作，真实触控尚不计通过。


### 原生 Main 的注册能力桥接（已实现，待线上运行验证）

真实 CLI 核验表明 `swarm goal/verify/memory/connector` 是需要受管 Agent 身份的注册能力，普通终端不能直接执行；`agent capability --turn/--call` 还必须匹配真实运行中的宿主 tool_call。原生 Main 不能伪造 worker task/run 或冒用普通用户消息取得这些权限。当前按 turn 的执行适配只证明排队和原生调用，不代表已经能承担完整 Main 派工验收。

实现应给原生 Main 签发单轮私有能力上下文，绑定 owner、project、原 Main CID、turnId、leaseEpoch、provider generation 和真实 provider ID。通过现有 `agent capability --context` 入口携带，原生进程无需重启或注入全局环境。能力服务必须在每次调用与执行期间重新校验原 turn 仍在运行、lease 和 provider generation 未变、来源上下文仍被接纳，拒绝跨项目、旧轮次、换实例和停止后的调用。该上下文与 worker 的 task/run 上下文分型并签名，不能相互转换。

通过原工具注册表以 Main 角色调用，保留原 source message、turn、toolCall 和项目身份；幂等键固定为 turn + requestId，参数变更拒绝，已知结果复用、未知结果不重放。仍由现有工具执行派工、记忆、数据和验收约束；不得新增直接数据库写入口或放宽发布授权。实际原生 Main 完成注册能力读取、一次原成员派工、读产物和独立验收后，才能认定接管机制跑通。


实现模块为 `tools/native_main_capabilities.py`。复用现有私有上下文目录与签名基础设施，但独立验证 Main 的原 CID、project、running turn、leaseEpoch、provider generation；worker 上下文不能取得 Main 身份。`NativeMain` 每轮把私有文件路径加入实际原生提示，HTTP 入口按带签名的上下文类型分派。调用进入原 `ToolGateway`，保留策略、来源、工具记录、进度与结果，不另造数据库写入口。`TurnJournal.finish` 保留已实际执行的能力调用及对应工具结果，不把它们交还 Core 二次执行。

已验证实际 Runtime 原 Main 队列→受控 CLI 端口→HTTP 签名上下文→真实 Swarm 状态→原 Main 最终回复，普通正文和强制 reply 两种模式均覆盖。Native Main 不直接调用最终 reply，最终交付仍由宿主完成。身份变化/结束/停止会拒绝新调用并取消运行中的能力；未知回执保留且不重放。原生最终回复、能力成功、成员成果与独立验收仍是不同事实。

前端模型/停止命令与正文消息使用分开的幂等存储，点击模型按钮不会丢掉正文未知发送的旧键或冻结 OKR 上下文；前端全量现为1914项通过。最初完整检查在旧 CLI 参数测试夹具处失败，已独立复现并更新期望为 `--identity`；该次未计通过。本轮能力桥接、原生 Main、宿主命令、协作策略及旧专业成员能力合计78项专项通过；重新执行最终 full。


### 最终接线补充

公共 `agent capability list/show` 面向 worker，不能作为 Main 专属操作的发现入口。原生 Main 的交接提示改为先用签名上下文调用现有 `tool_list`，按 Main 角色返回真实名称和 inputSchema；专项实际发现 `swarm_plan` 后再按相同上下文调用。该能力桥接当前17项专项通过，包含目录发现、两种最终交付模式、原工具回执及幂等、真实 stop 的撤权和取消。

浏览器的390px粗指针模拟发现 flex 子项的最小内容宽度会裁切回复和发送按钮，已在共用执行器聊天视图约束 `min-width:0` 与宽度。四档桌面宽度重新验证通过；compact 中聊天容器宽390px，输入框和发送按钮右边界361px，中心命中正常。只是浏览器模拟，不是真机触控验收。

原 Main 的同一候选实例 `2026-1118-1216-00ym` 已完成实际 Read×3 / Write 交接准备，文件为 `materials/2026-11-18/main/claude-takeover/takeover.md`，3740B、SHA256 `0e003864fe7b322a853d199c49046ddc3a59043d3e019c9cc58ddd7af03f276a`；Go 回执 succeeded、inputStopped=true、outcomeKnown=true，原初始化键再次 prepared=true。正式 Main 绑定仍未进行。
