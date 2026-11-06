# Swarm 投递与协调回合契约 v1（提案）

补充 [通信设计](swarm-communication-design.md)。这是实现前的契约，不是已开放的 API。

## 对照现有代码发现的约束

- `dispatch/runner.py` 在顶层任务结果落定时，已用 `task.completion:<runId>:<state>` 创建原 Main 的 completion turn。新增 handoff 通知不能再为同一结果创建第二次模型处理。
- `TaskRevisions.request` 明确拒绝 completion turn 的续派；已有回归验证 `TASK_STEER_USER_REQUEST_REQUIRED`。不能删除这条通用保护来实现自主协作。
- `ConversationService.wake_project` 最终进入 `Conversations.accept`，创建 user trigger / user message，并带 scheduled 元数据。这是现有外部日程入口，不能直接拿来将成员消息变成用户授权。
- `swarm_post` 的默认幂等键来自 turn/toolCall；这能防一次调用重复落库，跨回合恢复还需要保留业务 messageKey。

## 统一入口，复用现有完成回报

普通任务的 completion 机制保持不变。对已绑定项目、具有有效长期目标委托的 Swarm，使用同一个结果去重身份，把该次 Main 处理标记为 coordination，并携带原 completion 证据。handoff post 与完成回报关联到同一条递送记录。

独立 question/blocker 也进入这个协调入口；不会另外创建“通知 Main”的用户消息。收件箱与已有完成回报共用调度去重，用户消息仍按已有主对话入口提交。

| 情况 | 动作 |
| --- | --- |
| handoff 先到，执行结果未落定 | 保存消息，等待同一 run 的真实结果；不假称任务完成 |
| 完成回报先到，handoff 后到 | 关联同一结果/产物，沿用原处理轮次 |
| 原结果已处理，重复发相同 handoff | 返回原回执，不再次启动 Main |
| 新的补充证据或新问题 | 作为新业务消息；不能用旧 run 的成功为新文件背书 |
| 当前执行 outcomeUnknown | 保留问题与未知状态，走原任务对账，不新开成员重跑 |

已有 completion turn 若已进入运行，不中途改它的输入或触发类型；仅对新受管协调流程启用此契约。切换前的遗留回报通过实际 turn/result 回执对账。

## 协调授权：继承原委托，不制造新用户

受管派工时保存原项目 Main、目标与真实用户来源的引用；协调消息携带的是 authorityRef，而不是新的用户同意。

拟由宿主构造的信封：

```json
{
  "kind": "swarm_coordination",
  "projectId": "实际绑定项目",
  "swarmId": "实际绑定团队",
  "authorityRef": "受管目标委托引用",
  "messageIds": ["本批真实消息"],
  "taskBindings": [{"taskId": "原任务", "revision": "实际修订", "runId": "实际运行"}]
}
```

以上是字段说明示例，不能当作可提交的实例身份。project/Main/authority/taskBindings 由宿主取得并检查；成员和模型不能在请求中自行指定信任级别。

准入同时要求：

1. 原目标、派工来源与 Main 属于同一 owner/project/swarm，原用户来源未删除、未遗忘，目标未停止/撤销。
2. 仅允许 Main 在原目标与职责范围内指挥，继续原成员；成员问题不是新目标、账号或发布授权。
3. 仍检查最新 task/revision/run、会话状态、停止证明与 workspace 准入。不能因“自动协调”绕过未知执行结果。
4. 工具将 Main 的有界 assignment 与原用户委托分别保存。禁止把整个协调通知或旧用户长消息重放给成员。
5. 对具体内容/账号的外部发布仍核对既有授权与平台状态；团队事件不能替用户回答审批或扩大权限。

既有团队迁移先核对已保存的目标与派工回执；不能根据相似名称、成员自述或带 scheduled 的 user 记录猜测授权。普通 completion turn 仍不可续派；仅经过上述准入的 coordination turn 使用受限的协调能力。

## messageKey、递送与处理确认

Agent 的拟新增 messageKey 表示一条业务消息，重试时持久复用。缺省请求保持旧 turn/toolCall 去重兼容；需要跨回合恢复的 Skill 必须保存业务键。

键按 owner/swarm/真实作者及来源任务身份分域；相同键与相同内容返回原消息，相同键改正文、接收人、kind 或 replyTo 返回冲突。旧任务的已提交消息可通过授权只读入口对账，不能借重试给新 run 追加工作。

调度器在同一运行时数据库事务中：核对原 Main 空闲/未等用户，领取当前待处理消息集合，记录 batch 与稳定递送键，创建原 Main coordination turn/job。消息集合到此冻结；之后到来的新问题留给下一批。进程在任一位置退出，恢复均沿用同一批和去重键。

Main 的 read 回执仅表示取得消息。handled 必须关联同群真实 reply、受管 steer 或明确的未解决决定；任务验收另走原有验证。已读但未解决的问题不从待处理视图消失。

Main 自己的回复不创建自身待处理；转发只保留消息引用与可信作者，不复制成一条 human 消息。协调失败保留批次和错误，等待真实恢复或新信息，不反复空转。

## 实现前必须通过的故障矩阵

| 故障/竞争 | 应有结果 |
| --- | --- |
| handoff 与 completion 任意顺序、各自重复 | 同一结果最多一个 Main 处理，不丢产物引用 |
| 落消息后退出、领取后退出、job 创建后退出 | 恢复原消息/批次/turn，无第二条业务投递 |
| Main 忙、等待用户、分支变化 | 保留待处理；领取时重核当前分支，不抢用户回复 |
| 来源任务被 steer、run 被替代 | 旧消息保持历史，不把旧结果应用到新任务 |
| 原用户来源被遗忘、目标撤销 | 不继承失效委托；保留可解释的未处理原因 |
| 成员正文声称用户同意或伪造 target | 仍按可信作者与原委托准入，拒绝越权 |
| Main 回复/确认后产生新事件 | 不自我唤醒；handled 与任务成功分开 |

源码基线专项只能证明现有保护；上述新协议需要实现后的故障注入与真实项目交接验收。
