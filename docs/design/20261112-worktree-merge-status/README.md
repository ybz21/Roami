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

## 关闭预检耗时优化

用户在部署后反馈检查接近十五秒。原实现每次关闭都顺序执行仓库级 Sync、文件快照和
全仓 worktree 列表。一次生产 HTTP 请求实测 16.439 秒；相同目录的隔离分阶段测量中，
Sync 为 8.921 秒、快照 0.946 秒、列表 0.080 秒、会话归属 0.012 秒。网络耗时有波动，
不能把这些独立测量简单相加视为前一次请求的精确分解。

### 产品设计与用户故事

- 已有合入证据时，关闭预检不等待远端连接；尚未产生提交的工作区也不需要联网。
- 合入后新增提交时重新检查当前 HEAD；未提交改动、忽略文件快照和其他会话占用仍保留。
- 尚未确认合入的分支即时获取目标分支，继续覆盖“GitHub 已合入，本地主干没更新”的场景。

### 技术设计

新增 `backend/worktree/close-preflight.go`。`ClosePreflight` 只读取当前工作区，重新验证
当前 HEAD 对本地目标引用的 ancestry / patch-id 证据。有确证或 HEAD 仍等于 StartOid
则直接返回；否则仅 fetch 记录的 base，再重新计算当前状态。沿用十秒网络超时和离线
退化行为；不再调用仓库级 ls-remote / List。未确认的分支遇到慢网络时仍可能等待。

HTTP 预检复用该入口，其他占用会话按归属快照计数，避免为计数加工每一个工作区。
文件快照及关闭时的生命周期校验保持原有语义，不用过期文件指纹缩短等待。

### 验收

- 隔离 HTTP 回归覆盖无联网的已合入检查、其他占用会话、新 HEAD 重新获取远端，以及
  原 ancestry / squash、断网、本地仓库、未提交改动场景。优化前网络调用断言失败，优化后通过。
- 空工作区带未跟踪草稿时不联网，仍返回草稿计数。
- 同一实际工作目录（含 695 MiB 前端依赖）的隔离完整 HTTP 预检为 1.036 秒，包含有效
  文件快照；单工作区合入检查为 0.035 秒，文件快照约 1.013 秒。这不是线上部署后的实测。
- 原始证据：`/tmp/roami-close-latency-baseline.json`、`/tmp/roami-close-phases-before.json`、
  `/tmp/roami-close-phases-after.json`、`/tmp/roami-close-http-after.json` 及
  `/tmp/roami-close-latency-test-before.log`、`/tmp/roami-close-latency-test-after.log`。
- 完整质量门禁重跑通过，日志为 `/tmp/roami-close-latency-quality-full-retry.log`。
  首轮失败于既有 Claude 后台通知测试，该项单独复测通过，随后全套通过；未改动该测试。
