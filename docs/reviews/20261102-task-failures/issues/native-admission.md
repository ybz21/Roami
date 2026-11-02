# fix(agent): native session 目标在 Tasks.create 接受后才后台失败

## 复现与证据

`Tasks.create(..., executor='native', target={'kind':'session','sessionId':'...'}, record_intent=True)` 接受并生成 task/attempt/job；`NativeExecutor.requires_workspace` 进入 `hold_workspace`，后者不支持 kind=session，抛 `NATIVE_TARGET_ADAPTER_NOT_IMPLEMENTED`。历史 2026-10-18 有 1 次，无工具启动。

基线 08ad956b：`agent-runtime/src/roami_agent/dispatch/tasks.py:104-132` 接受 session target，`agent-runtime/src/roami_agent/executors/workspace.py:48` 才拒绝。Main TaskRouter 的 session 路径走消息追加，是不同的调用边界。

## 影响与建议

已接受的后台任务必然失败；调用者无法在提交前修正目标。Tasks.create 边界应在创建持久记录前拒绝不支持的执行器/目标组合；已有 native 会话续作沿用原任务 revision/session API。不要默默新建目录、切执行器或发送到其他会话。

## 验收

直接调用 Tasks.create 的回归覆盖拒绝且 tasks/task_attempts/jobs 不增加；已有 native 会话续作与 CLI session 目标照常工作。先搜索了现有全部 issues；#429 是已实现的 native 持久会话功能，并未覆盖此 admission 边界。
