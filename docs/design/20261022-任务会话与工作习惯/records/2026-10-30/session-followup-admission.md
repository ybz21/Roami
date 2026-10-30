# 追加要求等待会话空闲

## 产品设计与用户故事

用户给原任务追加要求时，上一轮回报与工作会话的空闲确认可能尚未同步。
追加要求应保留并排队，空闲后在原会话继续；不能把尚未发送的请求显示为任务失败，
也不能提前宣布任务完成。取消排队后不再发送，发送结果不确定时不自动重复追加。

## 问题证据

截图对应任务的第一轮执行器回报为 succeeded，任务等待验收；追加后的第二轮执行记录
没有会话绑定，结果为 `SESSION_NOT_IDLE`，随后产生 `task.failed`。
原会话生命周期仍为 unknown，说明回报与执行就绪是两份独立状态。
本次仅只读核对现场，没有重放原任务、改写历史状态或改动用户会话。

## 技术设计

- `executors/roami_cli.py` 将明确的 `SESSION_NOT_IDLE` 交给调度器处理。
  Go 的 `continueSession` 在写入提交凭据与发送提示词之前返回此错误，因而允许重试。
- `dispatch/runner.py` 保留同一个 task、revision、attempt 和 Go launch key，将 job
  持久化回队列，间隔从 1 秒退避至最多 30 秒。等待不重复消耗执行步骤、不重复发布
  preparing 事件、不产生失败回报或完成通知。
- 恢复时重新排队尚未完成的空闲等待操作；同一 launch key 仍由 Go 的提交凭据去重。
  取消与 revision 校验优先，其他拒绝保留原失败处理。发送结果不确定时只观察原提交，
  不进入空闲等待重试路径。已有的完成校验与用户验收要求保持有效。
- `tests/test_session_submission.py` 覆盖真实任务追加、单 worker 调度、重启、取消竞争、
  旧成果保留、未知发送结果与不可恢复的会话拒绝。
- `tests/session_continuation_scenario.py` 通过真实 Go CLI 模拟可信生命周期回调：
  两次忙状态拒绝都没有发送；空闲后只提交一次，最终回到原对话并等待验收。

## 验收

Claude、Codex 的 Go/Python CLI 联测通过；测试不调用模型提供方。
`test_session_submission.py`、`test_coding_executor.py` 和 `test_task_revisions.py`
共 53 项针对性回归通过；新增的 8 项全部执行，无跳过。
`scripts/dev/quality/check.sh quick` 通过：Go 全量测试、Python lint/format、
Python 2471 项通过（47 项跳过）、前端 i18n/hover/typecheck 以及密钥扫描均通过。
PR 发布前的 `check.sh full` 通过：Python 2474 项通过（47 项跳过），包括后补的
3 项不可恢复拒绝回归；Go 全量、前端生产构建及其余门禁通过。
测试实例通过 `isolated-roami.sh` 隔离并使用同一入口清理。
本次没有 Web UI 修改；未更改线上实例或原截图任务的历史状态。
本文为开发验收记录，使用中文，不属于产品界面的国际化文本。
