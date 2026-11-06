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

`SwarmMemberChat` 仅服务具有明确持久实例的成员；旧数据继续使用既有任务消息视图。身份键包含节点、项目、Main、成员、任务、revision、run 和实例完整绑定。只在该键变化或显式恢复时 GET 任务，不增加按成员轮询。加载取消且旧键结果不渲染；每次渲染用共享会话概览重新核对 CLI 存活、执行器和归属。

`swarm-member-session` 核对实例 taskId、conversationId 与独立 branch，任务/attempt 的 revision 和 run、执行器、项目、关闭状态。Roami 进一步核对 nativeSessionId / conversationId；`NativeSession` 的嵌入模式以预期任务、项目、conversation、branch、revision、open lifecycle 验证真实元数据。CLI 复用 `CodexChat` / `ClaudeChat` / `OpenCodeChat`，相同 session 名读取原转录。

全局 `ChatShell` 支持可注入的发送函数，成员消息走现有 Swarm messages 及原 workId/revision，不绕过任务追踪；不确定投递的命令键保留，重进页面仍使用同一个键。原生 Roami 复用现有 steer/CAS。CLI 草稿按节点/session 保存，团队内外共享原会话草稿；切换仅卸载当前组件，不新增后台成员轮询。

不改变 Main 会话、成员实例、历史、任务状态和来源数据。真实 Android 未授权触控，本轮仅能报告桌面及模拟紧凑布局证据，不能宣称真机验收通过。

## 验收记录

实现与验收中；以 PR 内最终检查、截图和部署回执为准。
