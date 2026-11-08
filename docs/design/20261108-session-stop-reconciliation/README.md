# 受管会话的停止对账

## Product Design

手动追加输入使原受管范围不再可信。默认状态仍是 unknown；不得用原生最终回答冒充原任务成功。显式 reconcile-session 只在同一个 Codex turn 的真实终止记录、原 provider/目录/进程身份和全部工具停止均可核验时，将原执行明确结为 failed（SESSION_SCOPE_CHANGED_STOPPED），保留原有未知事件和证据哈希。外部发布是否成功仍需独立平台回读。

## User Stories

- 原 Main/成员/provider 和文件不变；不重发已经发生的操作。
- 原执行失败后，同目录其他角色可继续，Main 可给原成员安排新的受管对账轮次。
- 仍有工具/子任务、错身份、改目录、新 turn 或证据变化一律拒绝；普通 status 不自动宽松接受手动输入。

## Technical Design

新增 roami agent execution reconcile-session --key。宿主在 launch/state/workspace 锁内读取原提交清单，复用原 Codex 严格转录扫描与进程停止检查，另开显式模式仅接受已匹配原提示词之后、同 turn 的追加输入。最后仍需真实 task_complete、完整工具配对、实际 final_answer、稳定原生文件与 provider 身份。二次检查文件哈希及进程后，保存已失败的停止回执，再恢复该实例 idle；重入只返回本次失败回执，不能覆盖其他执行。写入中断后按相同证据恢复，不能改变后来的 workspace writer。

OutcomeKnown=true 仅表示宿主已确定原执行因范围变化而失败；不是内容验收、发布成功、外部动作结果或助手声明的认可。InputStopped=true 来自真实 provider 与进程证据。

受管任务补充工作必须走 task_steer / swarm say；不要直接 session send。真实触发为 #804：Root 追加回执修正提示后命中 SESSION_PROMPT_MISMATCH，实际五条平台对象已独立确认，仍保持任务未知直到宿主对账。

## Acceptance

覆盖原未知保护、同 turn 追加、失败回执和原成员下一轮、同目录下一角色、重复对账、不完整/额外 turn/错误身份/活动工具/证据冲突。实际生产恢复与平台回读分别记录，测试不能代替。
