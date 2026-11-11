# Claude 原实例中断后的可信接续

## 产品设计与用户故事

工具审核拒绝命令时，Claude 可能留下缺失的 PostToolUse 回调。用户正式取消后，原生终端已经停止，宿主仍会显示取消中。本设计只为已经正式送达的取消补齐失败证明，让原成员在下一轮继续同一个 provider；不把部分执行或取消当成完成。

## 技术设计

`session-claude-interrupted.go` 提供只读原生记录证明与显式 reconciliation；普通 status 不隐式清理。入口仍为 `agent execution reconcile-session`，只处理有正式 interrupt-request 的 Claude 原轮次。

必须同时满足：

- 原 executor、provider、会话进程、工作目录、provider home、host proof、prompt hash、turn 和 writer lease 一致；取消请求匹配且已送达。
- 受保护的原生 transcript 包含该真实输入，UUID parent/logicalParent 可连通；每个同步工具都有原生 tool_result。后台、子智能体、未知工具或未完成工具一律拒绝。
- 原生压缩边界必须关联当前输入、无未完成工具，并有原生可见摘要。压缩不擦除工具责任。
- 最后一条有效对话记录为正式取消之后的原生中断标记，其后不能有新输入、回答或 API 请求。工具输出里出现相同文字不算中断。
- 缺失的每个 hook tool 都能逐一匹配上述已结束工具；系统进程检查也证明没有仍在执行的归属进程。
- workspace 写锁内再次验证原会话及两次稳定 transcript SHA，之后先保存原 lifecycle、工具结束证据与 SHA，再走标准 failed/result/lifecycle 路径。

结果为 `failed / CLAUDE_SESSION_INTERRUPTED`，包含 inputStopped、outcomeKnown、stopEvidence。保留原 provider、原文件和历史，不自动重发输入、不修改任务数据库或全局 busy。后续 provider recovery 必须重新校验该 SHA、原身份和未显式关闭状态。当前实现要求 reconciliation 时原物理会话仍存在，不扩展到任意丢失终端的恢复。

## 验收

专项覆盖正常中断、原生压缩、工具发现，以及伪造标记、异项目、异轮次、后台工具、未配对结果、活进程、writer 变化、显式关闭、证据变化和幂等接续。真实实例仅做只读探测：72 个原生工具均有结束结果，14 个缺失 hook 逐一命中；正式取消后的中断标记及进程停止证明成立。生产 reconciliation 与恢复后的真实命令执行需部署后独立记录，不在此提前声明通过。

## 2026-11-11 生产回读

PR #897 合入 `d1d445e433352a3abcc33ff37e28bb59bdfa8d52`，正常 full、最终提交 quick 和全部 CI 通过。冻结包 `okr-claude-d1d445e4` 同时包含 #893 的默认 provider home 修复和 #895 的 WorkBuddy 传输适配。

使用冻结包 CLI 的正式 reconciliation，将原数据分析 r4 记为 `failed / CLAUDE_SESSION_INTERRUPTED`，inputStopped 与 outcomeKnown 均为 true；保持原 SID `2026-1111-1950-00sz` 和 provider `6d4e9b67-ce0b-4287-b0ca-39106ca3fc67`。原生证据 SHA 为 `b801d0b9bacb8fc52b0e90e07b2e939765a7c94e47b129c918d16e839f43e585`。

随后正式 idle guard 通过，Agent 与依赖 Web 一并更新。健康版本、生产 index 与冻结包一致，网关模型配置前后相等；仅恢复本次持有的 Swarm 暂停 revision38，不触手机、不改任务数据库或手工 busy。证据保留在 `/tmp/okr-member-migration-20261111/{claude-r4-formal-reconciliation.json,team-deployment.json}`。

原 Main 已保存接续指令，明确继续原数据分析和运营成员、独立验收发布登记/Connector/真实看板，X01 unknown 不重放；当前仍需核验实际续派和真实工具执行，不能将消息保存或中断失败记作业务闭环通过。

### 真实写文件后的增量记录

r5 在原实例内实际写出一个探针文本，原生历史新增 `file-history-delta`（字段为 messageId/snapshotMessageId/trackingPath/backup/timestamp）。这是原生文件追踪元数据，和已支持的 file-history-snapshot 一样，不代表新工具调用。停止证明需要识别它；否则合法写入之后的取消会被未知元数据挡住。两种记录都仍受整个原轮次完整工具配对、正式中断、稳定 SHA、实际进程与 workspace 归属证明约束，不据此推断写入成功。

本轮另外发现自动审核仍有 `Request was aborted`，原生错误转储明确为 classifier unavailable/timed out；不能把传输修复或探针文本存在当 Python/Connector 已可执行。保留 auto 模式和原模型路由，继续定位原生审核延迟。
