# fix(execution): 执行待确认缺少生命周期 unknown 原因，观测结果无法追溯

## 复现与证据

sessionExecutionStatus 的 pane 身份不可读、生命周期文件缺失、launch key 不匹配、hook 状态 unknown、deadline 到期等分支全部返回 state=unknown，不带原因。Python CodingExecutor.record 把这些与 CLI 观测失败都记为相同 unknown；界面只显示执行待确认。

用户 2026-11-02 截图中的当前任务实际仍执行，Go status 和 lifecycle 均 unknown，且有一个 pending tool。没有历史 hook 输入留存，无法确定首次转 unknown 的事件，不能声称执行器退出或任务失败。

代码：`internal/agentexecution/session-lifecycle.go:401-445`、`:178-262`；`agent-runtime/src/roami_agent/executors/roami_cli.py:310-390` 的观测边界；`frontend/src/components/agent/AgentTasks.tsx:100-104` 显示规则。

## 建议修复

生命周期持久化首个安全的 unknown reason code；Status 返回 observationErrorCode；Python 在 observation_unknown 事件保留该码并按原因去重，观测恢复后保持原恢复语义。没有终态 result 时保留 unknown，不把进程存在当完成证明，也不把观测失败当停止证明。无需新增轮询或 UI 硬编码文案。

## 验收

丢失 lifecycle、错 launch、工具回调不匹配、显式 deadline 分支有不同公开码；未知状态保护仍在。相同原因不刷事件，原因变化可追踪，恢复 running 发既有恢复事件。历史未知任务无法从新字段恢复未保存的旧原因，报告明确限制。
