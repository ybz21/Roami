# fix(execution): 生命周期 unknown 时取消围栏失效，续作长期停在正在停止

## 复现

已绑定 Codex/Claude 任务先 busy，收到不匹配工具回调后 lifecycle.state=unknown；请求 Cancel 创建 cancel.json；同一 provider、turn、launch 的下一次 PreToolUse 仍返回成功。因为取消检查额外要求 state.State==busy，unknown 时跳过，任务继续执行新工具，TaskRevisions 等待停止而不推进。

## 证据与影响

用户 2026-11-02 18:36 截图：本次排查任务显示正在停止。只读核查发现原 task revision=1、state=cancelling、attempt.state=unknown 且无 result；Go status=unknown、lifecycle=unknown、tools=1、cancel.json 已存在，执行器仍在工作。没有把该截图计入历史已中断任务。

`internal/agentexecution/session-lifecycle.go:226-230` 的 busy 条件使取消失效；`agent-runtime/src/roami_agent/dispatch/task_revisions.py:223,315` 正确等待停止证据，因此不能用强制推进 revision 绕过。

## 修复建议与验收

同一可信 provider/turn/launch 下的 PreToolUse 即使 lifecycle unknown 也必须执行已持久化的取消围栏；不伪造停止、不删除 pending tools、不重放任务。覆盖 unknown + cancel 返回 SESSION_TASK_CANCEL_REQUESTED，未知状态保留，其他 turn/provider 不被误取消。部署后才影响现有会话，本次不直接改生产状态。
