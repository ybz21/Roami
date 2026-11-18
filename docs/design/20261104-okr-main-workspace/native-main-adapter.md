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

现有 `ConversationService` 的 `/model`、`/status` 和 `AgentConversation` 模型菜单仍读取全局 ModelSettings。需要接到当前项目 Main execution binding：显示 Claude/free，模型操作不得修改首页 Main。原生展示复用实际存在的 `ClaudeChat`/`CodexChat`、`AgentViewToggle` 与终端组件，通过 onSend 继续投递原 Main 队列。上述入口隔离及原生过程展示未完成前，不正式绑定线上项目 Main；后端首版不能当作全部切换完成。
