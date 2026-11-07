# 验收后的上下文身份与独立回传

关联 [#763](https://github.com/ybz21/Roami/issues/763)。真实 Main 完成成员验收后，消息预览和旧 session 回传在精简 turn 上抛 `KeyError: conversation_id`。X 的工作已结束，但回传未收尾，原任务下一轮仍等待同一会话。

## 产品设计与用户故事

Main 读完并验收当前交付后，应能继续流式回复，用户正常读取消息。已经投递的独立 session 工作可以在 Main 回合结束、停止或原任务推进后返回历史结果；结果仍未验收，不能作为新指令、当前任务成功或发布许可。

保留原会话、原回传业务键、任务和历史，不通过手改 busy/final_status 解除等待。用户遗忘或删除来源后，旧结果不能重新暴露该来源。

## 技术设计

- `storage/swarm_completion.py` 从宿主 turn/owner 查出真实 conversation，支持现有只传 id/owner 的调用者；若调用者另给 conversation 且不匹配则拒绝。继续核对当前任务/revision/run、本 Main 本回合的验收事件与原始终态，不放宽自验条件。
- `storage/context_admission.py` 分离来源可用性检查与执行准入。模型/工具执行仍检查停止、任务新鲜度及协调权限；来源检查保留遗忘消息、失效图像/附件和记忆证据的原约束。
- `SessionDispatches.report` 只接收已存在且同 owner 的回传，检查原来源可见及来源证据。它不再次执行旧 Main 工具，因此不以 Main 停止或 task revision 推进拒绝独立结果；原键去重、原 branch 和 `verified=false` 保持。真实任务验收仍走自己的当前轮协议。

## 验收

隔离重现完整 Main 审核流程后再调用精简准入、预览/分页和回传，覆盖接受与退回、伪造 owner/conversation、任务推进、停止与遗忘同时发生、重复键及拒绝时无通知写入。部署后以原 dispatch 和保留的最终 JSON 正常回传，再核对原 X 任务继续原实例；不人为完成或重建成员。

110项专项通过，包含上述完整审核/预览链路、实际HTTP回传、旧键去重、下一轮不被旧报告验收，以及现有来源审核、预览与通知回归。生产旧回传仍待标准修复包部署后对账；日志与验收记录使用 `/tmp/okr-completion-admission-20261107/`。
