# 团队原生对话与右侧任务工作区

关联 #713。入口保持群聊、Main、成员；Main 仍是原项目 Main，选中态不因目录重排而切换。

## 产品设计与用户故事

- 用户打开群聊讨论项目，Main 接收群聊请求并协调已有成员。
- 点击成员直接阅读、继续它的原有 Codex / Claude Code / OpenCode / Roami 对话，复用全局聊天组件和输入框。无需先打开任务再找会话。
- 右侧协作、任务互相切换，占其余工作画布的 40%，关闭时将全部宽度归还对话。手机继续使用单独二级页。
- 任务默认进行中，可切全部、待处理、已结束；选择按节点、团队保留。筛选只改变展示，不改变真实任务状态和验收。
- 未派发或身份不可确认时保留任务入口和找 Main 的恢复动作，不创建替代实例、不猜会话名、不回落首页。

## 技术设计

`SwarmConversations` 调整目录顺序。`ManagedSwarm` 持有工作区开合、页签、任务筛选；`swarm-task-filter` 依照现有任务列表的活跃/结束/待处理状态分类，运行中但执行器状态 unknown 进入待处理。

`SwarmMemberChat` 仅服务具有明确持久实例的成员；已注册的旧 CLI 成员即使没有 instance 字段，也可用原任务/轮次/run 与宿主持久项目 home、存活会话核验后复用原聊天；缺少可信身份则保留恢复入口。身份键包含节点、项目、Main、成员、任务、revision、run 和实例完整绑定。只在该键变化或显式恢复时 GET 任务，不增加按成员轮询。加载取消且旧键结果不渲染；每次渲染用共享会话概览重新核对 CLI 存活、执行器和归属。

`swarm-member-session` 核对实例 taskId、conversationId 与独立 branch，任务/attempt 的 revision 和 run、执行器、项目、关闭状态。Roami 进一步核对 nativeSessionId / conversationId；`NativeSession` 的嵌入模式以预期任务、项目、conversation、branch、revision、open lifecycle 验证真实元数据。CLI 复用 `CodexChat` / `ClaudeChat` / `OpenCodeChat`，相同 session 名读取原转录。

全局 `ChatShell` 支持可注入的发送函数，成员消息走现有 Swarm messages 及原 workId/revision，不绕过任务追踪；不确定投递的命令键保留，重进页面仍使用同一个键。原生 Roami 复用现有 steer/CAS。CLI 草稿按节点/session 保存，团队内外共享原会话草稿；切换仅卸载当前组件，不新增后台成员轮询。

不改变 Main 会话、成员实例、历史、任务状态和来源数据。真实 Android 未授权触控，本轮仅能报告桌面及模拟紧凑布局证据，不能宣称真机验收通过。

## 验收记录

#714 已合入、Web/CLI 已部署，桌面 205 文件 / 1501 项、四档宽度、紧凑模拟通过。真实项目发现两个旧 CLI 注册成员 instance 为空，继续补齐兼容并重新打开 #713；不能将新版协议 fixture 通过当作实际旧成员通过。

旧成员转入原生聊天时，将原 work/成员草稿一次性迁入同节点/原 session 的全局草稿；已有全局草稿优先，原文保留且相同旧文本不重复迁回。原不确定投递保留原 commandKey 和 taskRevision，绝不按最新轮次自动重写请求。


### 持久会话转录隔离

#715 的真实项目复验发现，虽然 X / Bili 的 session、task、run 和 providerConversationId 不同，旧 Codex 转录解析仍会因相同 cwd 而选择同一个最近更新文件。不能把不同 session 名或正确的输入投递目标当作历史展示已经隔离。

受管 Codex / Claude 的状态与转录接口优先采用精确 live pane 的持久 lifecycle provider 绑定，检查 server、创建代次、pane、PID/启动标记、目录/主机证明及运行状态，再按该 provider ID 唯一定位原转录。已有绑定但证明缺失、变更、文件缺失或重复时不回落同目录其他记录；传入的旧缓存 file 参数不能覆盖这条绑定。未纳入 lifecycle 的普通会话保留原解析路径。读取不创建或改写 state，不修改 Python runtime、模型路由或会话实例。

主机/目录证明算法保持原字节合同，提到既有 agentlifecycle 包供写入与只读投影共用。回归使用隔离虚拟 pane 与临时文件，覆盖同目录更新更晚的另一会话、缺失/重复 provider 文件、跨主机/目录/PID/执行器及 unknown 拒绝；真实生产验证要进一步检查两条不同转录文件和实际可读消息，未完成前 #713 保持打开。
