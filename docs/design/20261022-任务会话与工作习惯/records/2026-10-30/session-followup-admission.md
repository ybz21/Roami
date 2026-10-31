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

## 多执行器与追加前状态（2026-10-31）

追加规则按任务状态判断，适用于 Roami 原生 `native`、Codex `codex`、
Claude Code / CC `claude`、Pi `pi` 与 OpenCode `opencode`。原生任务继续原分支；
外部执行器继续原会话和提供方上下文，不因追加而切换执行器。

| 追加前状态 | 处理与验证 |
| --- | --- |
| 已完成 `succeeded` | 新建 revision，保留原验收记录；旧成功不能直接完成新要求 |
| 待验收 `waiting_user` | 允许追加，保留未验收约束，不能借追加自动接受旧成果 |
| 失败、取消、已知停止的中断 | 确认旧执行已停止后继续；旧失败属于历史，不污染新 revision |
| 排队、准备、执行、校验、取消中 | 先停止旧执行，再提交新 revision；停止未确认时不抢跑、不报新任务失败 |
| 结果未知或输入未停止 | 拒绝自动续接，不覆盖旧证据、不重放可能已经发送的输入 |
| 会话关闭中、已关闭 | 拒绝追加，不重新打开用户明确关闭的资源 |

`test_task_followup_states.py` 覆盖五类执行器与十种任务状态、停止/结果不确定、
关闭中/已关闭，以及旧回调不能决定新 revision。原生任务实际经过注入模型的执行循环；
外部执行器在共享调度回归中使用受控 CLI 回执。

`test_session_submission.py` 扩展到四类外部执行器与五种已结束/待确认状态，
逐一验证忙状态等待、重启、取消竞争、发送不确定和不可恢复拒绝。
`session-structured-continuation_test.go` 启动受控 OpenCode/Pi 协议进程，经过真实 Go
提交凭据和会话控制器，验证成功、失败、取消后的原会话续接、忙/未知拒绝、身份和权限
保留、取消输入不执行与幂等提交。既有 Codex/Claude hook 联测继续适用。
本轮补充验证，没有引入执行器专用的运行时分支，也没有调用真实模型提供方。
扩展的 Python 状态/等待矩阵与既有 revision 回归共 244 项通过；新增的
OpenCode/Pi Go 协议联测均通过，未跳过。

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

## Chrome 自动验收（2026-10-31）

针对运行时代码 `f747226c3fbc961c0809ad1c459e63804c79078e`，通过 `roami chrome`
操作构建后的真实前端、Go 网关与 Python 任务状态机。最终矩阵为五类执行器
`native/codex/claude/opencode/pi` × 八种追加前状态
`succeeded/waiting_user/failed/cancelled/interrupted/running/unknown/closed`，
共 **40 个场景、485 条断言通过，失败 0**。Pi 对应此前需求中 PAI 的暂定解释。
补充后的完整质量门禁为 Python 2696 项通过、47 项跳过，Go 与前端门禁通过。

浏览器验收检查了以下行为：

- 用真实按钮点击提交追加，检查按钮中心命中；已受理的输入清空，旧成果不充当新成果。
- 忙状态下原 revision 2 保持排队，空闲后执行；重试保留同一提交标识，实际接收一次。
  DOM 状态历史未出现新轮次误报失败；执行中的旧轮次停止确认前不提交新轮次。
- 正常场景均产生原 Main 对话的完成回报；原生与 Claude 的已完成场景检查 Chrome
  中回报文本、刷新后结果保留，并观察 6.8 秒，已结束详情没有继续轮询请求。
- 未知结果时拒绝自动重放，保留追加草稿，刷新后仍保留；已关闭会话禁用追加入口。
- 检查页面无横向溢出，另截取 412px 紧凑档排队与结束画面。

执行器的忙状态、接收和完成回执及停止信号由受控夹具提供，Main 与原生任务使用注入
测试模型；没有调用真实模型服务，也没有向真实外部编码器 TUI 发送输入。紧凑档为
Chrome 截图视口，未做 Android 真机触控验收。本轮没有修改产品代码。

测试在唯一回环主机地址、独立数据与 tmux 实例中运行；Chrome 确认安全上下文可用，
测试 Cookie 与线上地址隔离，没有修改真实任务或模型路由。验收后关闭本任务标签页，
停止测试服务，并通过原 `isolated-roami.sh` 入口清理该实例。

截图已上传 [PR #540](https://github.com/ybz21/Roami/pull/540) 的 `pr-shots` 分支：

- [追加后排队](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-540/chrome-claude-appended-queued.png)
- [执行回报待核验](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-540/chrome-claude-appended-finished.png)
- [紧凑档结果](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-540/chrome-claude-appended-finished-compact.png)
- [Main 对话收到追加回报](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-540/chrome-completion-reply-in-main.png)
