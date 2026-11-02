# fix(agent): 原任务续作从审计副本取附件导致旧截图与历史输入丢失

## 复现与影响

历史 42c1e20b… 的附图续作工具成功，原用户消息有 1 张截图，而 task.steer payload 和审计消息附件均为 0；operationId 可通过已有 task_user_request 反查源消息。当前 professional_brief 只读 origin_message_id 的副本；连续续作后也没有读取任务 sourceMessageIds 中的已授权输入。

代码基线 654e16f7：`agent-runtime/src/roami_agent/executors/professional_brief.py:12-56; dispatch/task_revisions.py:366-442; storage/task_request.py:8-46`。

## 修复与验收

从任务自身 lineage 与 task_user_request 解析真实来源，保留 taskId/工作区/执行器，输入文件去重并校验所有者、撤回/遗忘、完整性。native 分支续作也从真实来源复制附件。找不到已授权来源应明确阻断，不猜其他会话附件。覆盖旧记录、连续两次续作、纯文字增补及撤回。

## 去重与范围

已核对已有 issue：#418 为同任务/执行器关联，#398 为旧未知结果恢复，#595/#596 为运行时取消围栏与观测；本 issue 跟踪不同的交付边界或拒绝说明。历史任务只读取证，不向原会话补发旧图，不重放其业务。新修复追加到 PR #597，不合并或部署。
