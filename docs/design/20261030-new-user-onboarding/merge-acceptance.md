# 合入前验收

2026-11-01。实现提交 `bc2012a6`，基线 `892fc9f3`，包含 PR #564 至 #576。同步前将全部未提交改动备份到 stash `eb85c5007c63d352086a70e73664493847072446`，rebase 与恢复均无冲突。此前设计、实现和录屏记录保留为历史快照。

## 自动检查

| 检查 | 结果 |
| --- | --- |
| `scripts/dev/quality/check.sh quick`（提交钩子） | 通过，Python 2986 passed / 48 skipped，639.43 秒 |
| `scripts/dev/quality/check.sh full` | 通过；Go 全仓、Python 2986 passed / 48 skipped（785.65 秒）、ruff / 格式、前端静态检查和生产构建、密钥及文件策略检查 |
| 前端 Vitest | 157 文件 / 1154 测试通过 |
| i18n / hover / typecheck | 通过，4705 翻译键 |
| `scripts/dev/quality/review.sh main` | 无阻塞项 |
| `git diff --check` | 通过 |

跳过数按测试输出保留，不将跳过写成通过。日志：[提交钩子](/api/file/tmp/onboarding-pr-commit.log)、[完整质量门](/api/file/tmp/onboarding-pr-quality-full.log)、[前端测试](/api/file/tmp/onboarding-pr-vitest.log)、[策略审查](/api/file/tmp/onboarding-pr-policy-review.md)。GitHub CI 与自动语义审查在对应 PR 中跟进；本文不把本地检查写成远端已通过。

## 截图与运行证据

改前页面从 `892fc9f3` 的前端源码独立构建；改后使用本工作区生产构建，连接同一个专用隔离节点。新用户配置、项目为空，未调用外部模型或用户原生账号。

- [改前：首页桌面](/api/file/tmp/onboarding-before-home-desktop.png)
- [改后：首页桌面](/api/file/tmp/onboarding-after-home-desktop.png)
- [改前：首页 Android](/api/file/tmp/onboarding-before-home-phone.png)
- [改后：首页 Android](/api/file/tmp/onboarding-after-home-phone.png)

Android 使用 Redmi Note 8、392 CSS px、LAN HTTPS，实际点按登录和首页；没有用桌面缩窄视口冒充真机。页面复用的 Pi / OpenCode、主模型高级配置、项目克隆触控，以及 63 个布局组合与目录一致性证据见[页面复用验收](page-reuse.md)。视频中的项目、会话及完成状态是产品接口的真实回执，模型和执行器为本地测试替身，见[全流程录像](walkthrough-video.md)。

截图通过 `scripts/dev/pr-shot.sh` 上传 PR 的 `pr-shots` 路径，不提交图片到主分支。媒体本机链接需要 Roami 登录态。

## 清理

本轮截图使用 `/tmp/roami-onboarding-pr-before-00ac`，服务进程按专用 `ROAMI_HOME` 精确停止，tmux 仅由该目录的 `isolated-roami.sh --stop` 清理。只关闭本轮浏览器页，移除专用 ADB 转发及 UI 检查文件。未修改用户主配置、部署服务或清理其他工作区。
