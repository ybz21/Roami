---
name: cc-swarm
description: 使用现有 Roami Main 编排蜂群，拆分可验收的任务、选择 Codex/Claude/Roami 执行器、处理依赖与修订，并汇报验证结果。
user-invocable: true
---

# 蜂群协作

指挥是当前 Roami Main 对话。通过工具发现 `swarm_create`、`swarm_plan`、`swarm_status`、`swarm_post`、`swarm_control`、`swarm_dependencies`，使用既有受管任务执行、回报和验收。

1. 明确目标、交付物和验收标准。用户已授权的工作直接推进。
2. 用 `swarm_create` 创建协作；来源绑定当前用户消息和 Main 对话。
3. 用 `swarm_plan` 提交有名称、执行器、目标和验收标准的成员项。执行器支持 native（Roami）、codex、claude、opencode、pi；按实际安装、认证和能力选择，失败不静默更换。
4. 依赖明确指定上游成员与 task revision；只有指定版本已验证成功才派发下游。最终整合项设置 `integration: true`，消费全部必需上游结果。
5. 通过 `swarm_status` 查看当前任务、群聊与阻塞。成员讨论用 `swarm_post`，不能据发言或终端文本改变验收状态。
6. 完成回报沿现有 completion turn 回到原 Main。返工使用 `task_steer` 继续原任务，保留执行器、工作区和会话；依赖版本变化先确认停止，再用 `swarm_dependencies` 重新绑定。
7. 用户只需要看到验证结果、可用交付物和下一步。未知执行结果先恢复原任务，不能新建会话补跑。

CLI 与 Web 使用同一服务：

```bash
roami swarm new <名称> --key <持久请求键> --goal "目标与验收标准" [--main-conversation <对话ID>] [--dir <目录>]
roami swarm ls
roami swarm status <sw-id>
roami swarm plan <sw-id> --file plan.json
roami swarm dependencies <sw-id> --file dependencies.json
roami swarm control <sw-id> --file control.json
roami swarm say <sw-id> --file message.json
```

写请求都带 `commandKey`；计划、依赖和控制另带 `expectedRevision`。未知投递重试保持原键和原 revision。专业执行器发群聊使用宿主提供的 taskId/runId/taskRevision 与 `post --file` 私有回传通道，不能冒充其他成员。

暂停只停新派发；停止走现有取消与停止证据；归档仅整理展示。会话、文件和工作区的关闭沿用既有资源收尾流程。旧的 add/adopt/done/activate、手动移动卡片与独立 Claude 指挥已移除。
