# 原 Codex 直接消息完成后的续派恢复

关联 #764、#763 和 #761。真实 X 成员已经完成直接消息的工作，但完成通知遗漏，宿主仍为 busy、无 launchKey，下一轮受管续派一直等待。回传接收与执行器空闲是两份不同事实：#763 修复 HTTP/来源准入，本段恢复原执行器的可信完成证据。

## 产品设计与用户故事

Main 继续原成员时，应恢复同一 provider、同一长期会话，不把已完成的工作再做一次。页面保持原 Main/群聊/成员入口。无法证明停止或身份已改变时保留等待；屏幕上的 Ask Codex 和成员自述都不能代替宿主证据。

已读到直接消息结果，不等于下一轮已经完成；恢复只允许正常续派准入继续检查，不代替 Main 验收。

### 续派入口

用户让 Main 继续 X/B站成员时，必须续派原 task，由受管协议恢复同一成员。`session_send` 只用于无受管任务的旧会话；不能因为成员已空闲、上一轮成功、目标是别名或属于另一个项目而绕过这一规则。直接打开成员的原生对话仍使用既有用户输入能力。

Python 在新投递前通过 CLI strict resolve 取得稳定 session ID，在同一写事务里复查来源准入与所有历史 task_attempts 的绑定。命中受管会话时返回 `TASK_SESSION_BINDING_REQUIRED`，不暴露其他项目的任务内容。等待解析期间来源被忘记、任务绑定新增，也必须拒绝；不得产生一个可以稍后误发的 dispatch。

已经 delivered/unknown 的旧投递仍以原 request digest 和回执重放，不重新解析已关闭的会话、不再次提交。尚未投递的 prepared 记录需要重新过准入。Go 在原 lifecycle 的 state.lock 内检查 launchKey/completedLaunchKey，拦住已启动但 Python 尚未落下 session_id 的窗口；检查与实际提交持有同一把锁。明确的路由拒绝记录为 failed，不能误记为“可能已投递”。

Main 的工具说明同步强调 task_steer 和原团队身份；拒绝不自动新建实例或改走另一个 session。此防护是自动审核、发布、取数闭环的前提，不代表发布通道已经接通。

## 技术设计

`internal/agentexecution/session-message-completion.go` 复用已有 `codexCompletion` 的完整源记录校验：原 provider/目录、当前 turn/输入哈希、最后 task_complete、未结调用与最终文本匹配、稳定完整且不可公开写的原文件。只处理 busy 且无 launchKey、无未结工具的 Codex 直接输入；未知、停止、受管执行、其他 provider/目录或新用户输入保持拒绝。

`continueSession` 持有原 state.lock，在已有续派检查中尝试恢复。原进程身份和 scope 必须仍匹配，并通过 `sessionProcessesStopped`；不从 TUI 文本推测。成功将 provider/turn/源哈希/完成时间持久记录在原生命周期目录，再以正常原实例协议继续。本段不生成旧 task 成功回执、不伪造 hook、不创建替代实例、不修改业务库 busy。

历史内部 Codex 线程继承的完成通知可留诊断，不取代根 provider 证据；发生真实身份变更形成 unknown 时仍拒绝恢复。新的受管任务有自己的业务键和结果，旧直接消息不能完成它。

## 验收

专项覆盖真实完整源、旧内部线程通知、身份变化、未完成/错输入/错turn/provider/目录、后续用户输入、未结工具/子智能体、停止、受管执行、失效进程证明与冲突证据。成功必须仍为原 session/provider，重放不重复提交，新任务结果仍为空；拒绝不得新增提交或重写原生命周期。

### 原实例恢复已上线

PR #765/#766 已合入，官方树 `629012bf281406653c5618022079211c58a768d7` 标准包已部署。原 X 的旧直接消息按原 JSON 成功回传，同 key 重放复用原 event/message，`verified=false` 保持不变；Go 恢复精确原 provider 的完成证据后，原 r10/run 在同一个长期会话继续完成。

原项目 Main 实际读取当前 manifest、正文、来源和 PNG 字节后，通过受管 `swarm_verify` 接受 r10；同一 Main turn 继续预览、追加团队记忆并正常结束。记忆保留旧字节前缀，群聊回告作者是原 Main。一次上游模型 401 保留为历史，未修改模型路由或凭据；后续正常回合已完成。这里只是制作验收，没有发布声明。私有证据位于 `/tmp/okr-direct-message-recovery-20261107/`，#763 已据此关闭。

### 本段路由防护候选

Python 专项还应覆盖稳定 ID/label/tmux ID、同项目/其他项目、历史成功/取消成员、等待解析期间的新绑定与来源遗忘、prepared 重试、Go 明确拒绝的 failed 回执，以及绑定变更/会话关闭后 delivered/unknown 原回执重放。Go 专项验证 launch/completed/initial 状态均在输入与不确定回执之前拒绝。完整门禁、正常钩子、PR/CI与隔离验收记录位于 `/tmp/okr-managed-routing-20261107/`；未部署前不把这一段记为线上通过。
