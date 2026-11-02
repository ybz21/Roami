# fix(agent): 续作版本过期与会话失效拒绝缺少可操作恢复说明

## 复现与影响

历史 task_steer 有 1 次 TASK_REVISION_CHANGED，target_resolve/session_send 有 3 次 SESSION_TARGET_NOT_FOUND。当前 Gateway 对这些返回裸错误，未解释是否接受、新版本怎么核对以及不能猜其他会话；TASK_OUTCOME_UNRESOLVED 的恢复文字又一概要求等待停止，无法区分停止已证实但外部结果未知。

代码基线 654e16f7：`agent-runtime/src/roami_agent/tools/gateway.py:400-526; dispatch/tasks.py:497-503`。

## 修复与验收

返回明确的 executionStarted=false、恢复说明，要求读取原任务实际 revision 后重审要求，保留 taskId/执行器/工作区，不自动换版本/会话或重放未知写入。将 stopConfirmed 与 outcomeKnown 分开（已有 #398 的一部分），为未知外部结果给核验路径而非盲等。覆盖错误未产生新任务/投递、状态字段和提示保存。

## 去重与范围

已核对已有 issue：#418 为同任务/执行器关联，#398 为旧未知结果恢复，#595/#596 为运行时取消围栏与观测；本 issue 跟踪不同的交付边界或拒绝说明。历史任务只读取证，不向原会话补发旧图，不重放其业务。新修复追加到 PR #597，不合并或部署。
