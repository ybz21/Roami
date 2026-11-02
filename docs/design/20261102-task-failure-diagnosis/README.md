# 后台任务失败与中断分类修复

## Product Design

后台任务只有在确有未确认副作用或停止证据不足时保持 interrupted；已证实停止的普通异常按失败回报。错误详情保留安全的类型与错误码原因链，明确区分显式执行 deadline、上下文中断与通用超时。

## User Stories

- 用户能区分失败、取消与结果未知，并沿用原任务的安全续作流程。
- 运维能从 task attempt 详情找到内层公开错误码，不需要猜测混合 summary。
- 不支持的 native session 目标在接受前拒绝，不创建注定失败的后台任务。

## Technical Design

- `executors/workspace.py`：普通 Exception 的停止判定读取 stopped 回调；明确 TOOL/MCP unknown 即使没有 pending row 也不转成已知结果。取消与 BaseException 保持原保护。
- `dispatch/runner.py`：异常边界写入 errorCode、exceptionType 和至多八层去重 causeCodes；禁止原始异常文本。边界 TimeoutError 用 EXECUTION_TIMEOUT，避免推断必然是模型或任务 deadline。
- `executors/project.py`：复用 public_error_code 校验结构化 CLI 错误，保留合法非 PROJECT 前缀码。
- `dispatch/tasks.py`：native session 目标在持久化前拒绝；已有会话消息追加和原任务续作路径不变。
- `internal/agentexecution/{execution,structured-process}.go`：两种 CLI 执行路径共用 context.Err 分类；cancel.json 仍优先归 cancelled，输出证据保留。

- `session-lifecycle.go`：unknown 状态仍执行同 provider/turn/launch 的取消围栏；持久化首个 unknownReason，Status 以 observationErrorCode 表达观测故障，未知仍不当作停止。
- `executors/roami_cli.py` / `dispatch/tasks.py`：在既有观测事件保留公开原因，按连续同原因去重并向任务状态详情回传；不增加轮询。

## Acceptance

[排查报告、频次与验收记录](../../reviews/20261102-task-failures/README.md)。仅修改当前分支，不部署、不合并、不重放历史未知任务。
