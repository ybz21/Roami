# 完成并关闭：停止执行与清理工作区

## 产品设计

“完成并关闭”接受运行中的任务；一次确认后由后台持久作业停止任务树、关闭原会话并清理该任务创建的 Git worktree。页面显示收尾状态，结束后停止轮询。离开页面、重复点击与运行时重启不应重复创建关闭作业。

先按现有交付物收集规则保留产物，再清理工作区；会话正文、执行记录与交付物存储保留。主仓库、用户指定目录、复用的工作区不由关闭流程删除。未提交改动、未确认停止的执行、其他会话仍使用的目录都会保留，并显示可重试的处理提示。移除 worktree 后，保留尚未合入的分支；任务未产生提交的临时分支与已合入分支可以删除。

## 用户故事

- 用户确认结束当前任务后，不必先停止本轮、再关闭会话、最后手动清理 worktree。
- 用户离开任务页后，后台继续收尾；再次打开能看到关闭结果或明确的恢复动作。
- 同时执行其他任务时，关闭一个任务不会删除其他任务使用的目录或未提交改动。

## 技术设计

- `TaskSessions.request` 在同一事务校验 owner、revision、runId，设置关闭围栏、取消运行中的任务树与排队续改，写入幂等 `task.close_session` 作业。
- `Scheduler` 为关闭作业保留独立控制槽，并优先安排验证收尾，避免并发执行槽满时新任务抢占停止后的空槽。
- `TaskSessions.advance` 从叶子到根收尾任务树，复用已有停止证据、资源释放、CLI 会话身份和结果检查。只有完成实际关闭及清理后才写 `closed`；运行中关闭不改写为任务成功。
- `TaskWorkspaceCleanup` 按已有交付物规则保留文件，再调用 Go `agent execution cleanup --key`。Python 不自行运行 Git 删除工作区。
- Go 仅清理原 launch 创建且仍匹配注册身份的 worktree，持有工作区写入锁，复用 worktree 服务的占用和脏状态检查。会话停止收据按 tmux 资源身份复用，使后续修订关闭原会话后仍能清理初轮创建的 worktree。
- Web 复用原确认弹窗，增加收尾与恢复文案；仅在收尾未结束时继续观察任务，完成或失败后停止轮询。

## 验收

使用离线模型夹具、独立数据库及 `scripts/dev/isolated-roami.sh` 启动的私有 tmux 实例。未调用真实模型，未把用户会话当测试数据。

- Chrome 桌面与 Redmi Note 8（Android 10，DPR 2.75，compact/coarse）：真实点按“完成并关闭”，运行中的任务停止，关闭状态变为 `closed`，对应真实 Go 创建的 worktree 被移除；另外两个运行任务的 worktree 保留。
- 手机通过 ADB 真实点按、滑动；内容 scrollTop 从 149 变为 0，执行过程/对话页签可切换，页面宽 392 CSS px，无横向溢出。测试复用实际 NativeSession 和 MobileSubPage；不宣称覆盖首页底栏等未改区域。
- Go 回归覆盖停止证据、脏改动保留、分支改名、未合入分支保留、空临时分支删除、指定目录保留、重复清理；既有真实 tmux 的 Codex/Claude 常驻会话测试继续通过。
- Python 回归覆盖权限与修订校验、重复请求、服务重建恢复、续改互斥、任务树收尾、清理失败重试、运行中关闭、并发槽满时仍能结束。
- 前端回归覆盖运行中关闭入口、异步失败与重试、收尾期间观察以及关闭后停止轮询；typecheck、i18n、hover 和生产构建通过。

本机证据（一次性产物不提交主分支）：`/tmp/roami-close-desktop-confirm.png`、`/tmp/roami-close-desktop-after.png`、`/tmp/roami-close-phone-confirm.png`、`/tmp/roami-close-phone-after.png`、`/tmp/roami-close-acceptance-results.json`。全量与门禁日志位于 `/tmp/roami-close-*.log`。

最终检查：`quality/check.sh quick` 通过（Python 全量 2415 通过、44 跳过）；另补的关闭权限/任务树回归与停止链路共 47 项通过，Go 全量通过，前端 147 个文件共 1094 项通过。生产构建保留已有大包提示，无构建失败。验收后已关闭测试服务器、私有 tmux 实例并移除本次 ADB 转发。
