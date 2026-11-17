# 无回报核对与停止挂起：2026-11-17

## 审查结论

1. 原黄色提示仅由 unknown 状态触发，却声称已有回报和文件；确认入口又依赖 provider_transcript 回报存在，无回报的任务没有核对入口。
2. 截图任务已有 cancel.json，没有 interrupt-request.json 或终态结果；宿主返回 `SESSION_COMPLETION_MISMATCH`。留存根轮次已经完成，21 个残留工具标记均有结束记录，其中两条是失败的 MCP 调用。旧解析器只识别 CommandExecution，MCP 始终没有被计入完成证据。

新增单独的状态核对入口，保留人工成果验收边界；停止中的任务也能主动核对。主线提交 `4e10eab1` 已补齐 MCP 结束记录解析，本次同步并复用该修复，使已有取消意图在真实停止证据齐全后可收敛为取消；本次分支只保留独立核对入口与其回归。

本次没有扩大未知状态下的按键或信号投递权限，没有手工清空生命周期、工作区围栏或工具列表，没有重放原任务。

## 回归验证

- Go 基线反例：12 个 MCP 子场景中，完成、失败、取消后完成这 3 项在修复前失败。修复后全部通过（本次独立复现后同步了同等主线修复）；缺服务/工具、仍在运行、错误线程/轮次、结束晚于最终回复、重复记录、未结束子智能体、存活进程继续拒绝完成。
- Go 定向执行包含 Codex 完成、取消和精确中止回归，完整输出在 `/tmp/task-execution-recheck-20261117/go-regression.log`。测试使用独立 tmux 实例及独立 `tmux-spawn-*.scope`，不把因环境缺 scope 而跳过的运行算作通过。
- 用修复后的证据解析函数只读核对截图任务留存记录：21 个工具标记均有相应结束时间，真实进程停止证明成立。该检查不调用 Status 写回、任务验收、按键或信号接口；未修改生产数据库、结果文件或生命周期。
- Python 定向 48 项通过，覆盖无回报核对、unknown/stopping 取消状态、状态恢复、停止证据不足、网络异常、owner/revision/runId、缺失身份以及不允许传入 accepted 字段。找到成功结果进入 waiting_user；取消中的已停止任务保留取消语义。
- 前端全量 259 文件、1,897 项通过。任务组件覆盖无回报/文件、准备中、执行中、取消中、重复点击互斥、核对后单独验收、失败保留回报/文件/草稿与重试。

## 浏览器与真机

使用实际 React/Ant Design 组件与模拟任务 API，宿主和 Python 证据流另由上述回归验证。测试页面与脚本保留在 `/tmp/task-execution-recheck-20261117/`。

- 桌面 Chrome：320、390、820、1100、1280、1920、2560、3440 CSS px 均无文档横向溢出，核对按钮首屏可见且命中正确。中英文、深浅主题检查通过。
- Redmi Note 8 真机 Chrome，HTTPS LAN、392 × 766 CSS px、compact/coarse：按钮高度 44px、命中正确、二级页返回栏和底栏可见。以 CDP touchStart/touchEnd 实际点按核对和单独验收；失败重试保留文件；真实合成触摸滑动使内容 scrollTop 从 0 增至约 319.64。
- 核对请求只含 revision/runId，确认请求另行携带 accepted；核对不发送 cancel 或 verify 请求。
- 机械设计检测无新增问题。截图保留在上述目录，PR 图片通过 pr-shots 上传，不提交到 main。

本次尚未替换运行中的服务；源码修复与原任务线上状态恢复分别验收。

## 自动核对补充

用户要求此类情况自动核对。后台原本只循环读取 status，没有主动调用手动入口使用的 reconcile-session。本次将证据核对接入既有监控，不增加新的轮询器、前端轮询或任务重放。

新增 23 项回归覆盖无回报的准备/运行/取消/中断状态、成功后仍需用户验收、明确停止标志缺失/为 false、按完成时间退避与 60 秒上限、每轮两次额外调用上限、多个任务依次获得核对、恢复时重置重试、监控重启、淘汰旧 attempt、核对前后 revision/attempt/终态变化，以及正常运行/不支持的执行器不增加核对调用。实际启动后台监控循环，在没有页面请求时也能自动核对并唤醒验收，仍保留待验收状态。自动核对、手动核对、编码执行器、续派、资源释放和遗忘取消兼容性回归合计 265 项通过。

原始回归输出保留在 `/tmp/task-execution-recheck-20261117/auto-combined-regression.log`；下方首次 full/quick 记录保留为历史，自动核对改动另做最终门禁。

## 首次手动核对门禁

同步主线 `4e10eab1` 后，代码提交为 `19239baa`，quick 与 full 均通过：

- Go 全仓测试通过，使用独立 `tmux-spawn-*.scope` 及隔离 tmux 实例；首轮未分离进程 scope 时，既有取消证据回归出现一次观测不确定，分离 scope 后完整门禁通过，未放宽停止判定。
- Python 全量两次均为 4,937 passed、48 skipped、6 subtests passed；quick 耗时 1,954.09 秒，full 耗时 2,001.85 秒。跳过项不算作验收成功。
- 最终前端全量 259 文件、1,897 项通过；typecheck、i18n（6,001 keys）、hover、Vite 生产构建与压缩产物检查、秘密扫描、暂存文件策略均通过。
- 原始日志：`/tmp/task-execution-recheck-20261117/commit-integrated.log`、`quality-integrated-full.log`、`vitest-integrated.log`；截图与 `ui-results.json` 同目录保留。

## 自动核对最终门禁

自动核对代码提交 `086db4a9`。相关回归 265 项通过后，quick/full 全部门禁通过：

- Go 全仓检查通过；两个门禁均在隔离 tmux 实例与独立 systemd scope 中执行。
- Python 两次均为 4,960 passed、48 skipped、6 subtests passed；quick 耗时 2,114.91 秒，full 耗时 2,123.84 秒。
- typecheck、i18n、hover、Vite 生产构建与压缩、秘密扫描、暂存文件策略均通过。自动核对阶段未修改前端代码，原界面阶段的 1,897 项前端测试和 Android 真机证据保留。
- 原始日志：`/tmp/task-execution-recheck-20261117/auto-validated-commit.log`、`auto-validated-full.log`、`auto-combined-regression.log`；实际回归输出截图为同目录 `auto-regression.png`，发布至 PR 的 pr-shots 图片分支，不进入 main。

本次仅更新源码和 PR，未替换运行中的服务，也未代用户验收任务成果。
