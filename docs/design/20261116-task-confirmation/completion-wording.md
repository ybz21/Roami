# 完成确认文案

## 产品设计

后台任务的确认针对结果是否完成。执行本身不增加授权步骤；界面不再把宿主尚未核对结束的状态称为「执行待确认」。任务列表与详情统一显示「完成待核对」，提示用户查看回报与文件。按钮使用「确认完成」，实际结束状态仍由宿主核对，不能凭回报直接标成功。

## 用户故事

- 我能分清任务正在等待结果验收，而非等待允许执行。
- 我在任务回报旁确认完成，宿主负责检查任务结束证据。
- 无法核对结束时，我能查看工作会话并重试。

## 技术设计

沿用任务详情与列表的既有 i18n key，更新中文和英文文案。不修改任务状态、执行准入、验证协议或轮询。确认入口与执行结束核对沿用同目录 README 描述的修复。

## 验收

补充验收证据保留在 `/tmp/task-completion-wording-evidence/`，质量检查日志位于 `/tmp/task-completion-wording-*.log`。截图由 `pr-shot.sh` 上传，不提交主分支。

2026-11-16，基于确认入口修复 `968e885a` 复验最终代码：

- 本补充只改中英文文案与本文档。`quality/check.sh full` 使用 `QUALITY_BASE_SHA=968e885a`、`QUALITY_HEAD_SHA=HEAD` 对比本补充范围，通过；quick、typecheck、i18n、hover 与生产构建通过。
- 全量前端 Vitest：256 个文件、1,874 项通过。基础修复的完整 Go/Python 验证另见同目录 README；本补充没有修改这些运行时源文件。
- 桌面 1280、1920、2560、3440 CSS px：确认按钮首屏可见、中心命中正确，无文档横向溢出。
- Redmi Note 8 真机 HTTPS、compact/coarse：中文深色与英文浅色按钮均高 44px、中心命中正确；确认提交当前 revision/runId；未知结束状态显示错误且可重试；触摸滚动由 0 增至 340；返回栏与底部导航均可见。
- 浏览器使用最终实际 React/Ant Design 组件与隔离任务 API，未修改或验收用户线上任务。截图与断言：`/tmp/task-completion-wording-evidence/ui-results.json`、`phone-after.png`、`phone-en-light.png`；机械设计检测结果为 `[]`。
