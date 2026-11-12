# 关闭会话前刷新合入状态

## 产品设计

PR #905 已于 2026-11-12 21:29（北京时间）squash 合入远端 main，但关闭会话仍显示
一个未合并提交。关闭预检只读取本地远端跟踪引用和三秒列表缓存，没有触发远端同步。
本地 main 还停在合入前，项目页的同步也未必运行，因而旧提示持续出现。

关闭预检现在先刷新远端证据，再生成快照和收尾状态。沿用现有弹窗的已合入提示、
清理选项与未提交改动确认。

## 用户故事

- 在 GitHub 合入 PR 后立即关闭会话，无需进入项目页或手动 pull。
- 已合入分支上仍有未提交改动或新增提交时，保留相应警告。
- 远端不可达或仓库只有本地分支时，仍可依据现有本地证据检查并关闭。

## 技术设计

`SessionWorktreeStatus` 在确认会话属于 linked worktree 后调用现有 `Service.Sync`，
然后读取快照与列表。同步沿用十秒网络超时、禁用交互凭据输入及失败退化行为。
`Sync` 在所有退出路径失效列表缓存，使断网或无 origin 时也能重新读取本地状态。
不新增轮询，不移动本地 main，不改变合入判据或删除授权。

新增 `worktree-close-status_test.go`，通过隔离 launcher 管理真实 tmux 会话，真实 git
仓库与 bare origin 验证 HTTP 关闭预检。测试覆盖 ancestry、单提交 squash、缓存与远端
引用滞后、未提交改动、断网、本地仓库及后续提交。

## 验收记录

- 修复前：两种合并方式均在“远端已合入但关闭预检仍未识别”的断言失败。
- 修复后：同一隔离回归通过，确认本地 main 没有被移动。
- 原始日志：`/tmp/roami-close-status-before.log`、`/tmp/roami-close-status-after.log`。
- 完整 `scripts/dev/quality/check.sh full` 通过，包含 Go 全套与前端检查、生产构建；
  本次未触及 Python，按范围跳过其检查。质量日志：`/tmp/roami-close-status-quality-full.log`。
- 回归前后日志截图：`/tmp/roami-close-status-regression.png`，随 PR 上传到 `pr-shots`。
- 本次没有前端源码变更；验证对象为实际 HTTP 预检结果。
