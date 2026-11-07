# 原 Codex 直接消息完成后的续派恢复

关联 #764、#763 和 #761。真实 X 成员已经完成直接消息的工作，但完成通知遗漏，宿主仍为 busy、无 launchKey，下一轮受管续派一直等待。回传接收与执行器空闲是两份不同事实：#763 修复 HTTP/来源准入，本段恢复原执行器的可信完成证据。

## 产品设计与用户故事

Main 继续原成员时，应恢复同一 provider、同一长期会话，不把已完成的工作再做一次。页面保持原 Main/群聊/成员入口。无法证明停止或身份已改变时保留等待；屏幕上的 Ask Codex 和成员自述都不能代替宿主证据。

已读到直接消息结果，不等于下一轮已经完成；恢复只允许正常续派准入继续检查，不代替 Main 验收。后续还需在 Main 的 legacy session_send 入口禁止绕过受管 Swarm 成员续派，跟随 #658/#764 另段处理，当前不宣称该路由防护已经实现。

## 技术设计

`internal/agentexecution/session-message-completion.go` 复用已有 `codexCompletion` 的完整源记录校验：原 provider/目录、当前 turn/输入哈希、最后 task_complete、未结调用与最终文本匹配、稳定完整且不可公开写的原文件。只处理 busy 且无 launchKey、无未结工具的 Codex 直接输入；未知、停止、受管执行、其他 provider/目录或新用户输入保持拒绝。

`continueSession` 持有原 state.lock，在已有续派检查中尝试恢复。原进程身份和 scope 必须仍匹配，并通过 `sessionProcessesStopped`；不从 TUI 文本推测。成功将 provider/turn/源哈希/完成时间持久记录在原生命周期目录，再以正常原实例协议继续。本段不生成旧 task 成功回执、不伪造 hook、不创建替代实例、不修改业务库 busy。

历史内部 Codex 线程继承的完成通知可留诊断，不取代根 provider 证据；发生真实身份变更形成 unknown 时仍拒绝恢复。新的受管任务有自己的业务键和结果，旧直接消息不能完成它。

## 验收

专项覆盖真实完整源、旧内部线程通知、身份变化、未完成/错输入/错turn/provider/目录、后续用户输入、未结工具/子智能体、停止、受管执行、失效进程证明与冲突证据。成功必须仍为原 session/provider，重放不重复提交，新任务结果仍为空；拒绝不得新增提交或重写原生命周期。

当前为实现候选；完整门禁、正常提交钩子、PR/CI与标准包部署之后，才以原 X 队列和 Main 实际验收记录补充生产结果。私有证据位于 `/tmp/okr-direct-message-recovery-20261107/`。
