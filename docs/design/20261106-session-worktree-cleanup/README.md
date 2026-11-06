# 关闭会话后的 worktree 清理

## Product Design

用户选择关闭并删除 worktree 后，收尾不应被浏览器跳转或手机断连打断。
删除阶段失败时，会话可能已经关闭；再次提交原清理请求应能继续，不能永远卡在关闭会话这一步。
目录检查失败时应保留会话，避免产生新的孤儿工作区。

本次只修改后端关闭编排，不改变关闭选项，不批量删除历史目录。

## User Stories

- 选择随会话删除后，即使客户端断开，已接受的关闭请求仍完成收尾。
- 删除阶段失败后，用原会话 ID 和路径重试，可以继续清理已关闭会话的 worktree。
- 目标不是 linked worktree，或无法检查工作区时，在关闭会话前报错。
- 无法可靠观察会话状态时，保留 worktree。

## Technical Design

入口：`backend/api/worktree.go` 的 `SessionCloseWithWorktree`。

旧流程的 `wtCtx` 继承 HTTP 请求取消状态。`kill` 成功后请求取消，
后续 Git 调用直接失败，返回 `stage=remove, done=[kill]`，留下工作区。
重试时 `kill` 又因会话不存在报错，删除阶段不可达。
此外，旧预检忽略 `WT.List` 错误，主工作区、子目录、无效路径都会先关闭会话再报错。

修复：

1. 关闭编排使用 `context.WithoutCancel`，保留独立的 60 秒超时。
2. 删除前规范化路径，检查注册记录、主工作区和其他占用会话；检查失败即停止。
3. `kill` 失败后，用 `ls --live --json` 确认目标确实不在，才允许继续清理。
   观察失败、无效 JSON、缺少会话身份和目标仍在均不允许继续。
4. `backend/worktree/service.go` 的 squash 在无剩余改动时不创建空提交，允许合并成功后的清理重试。
5. 保留阶段化错误返回；不改变 worktree 服务的删除策略。

回归：`backend/api/session-worktree-close_test.go` 使用真实临时 Git 仓库，
通过替身 CLI 在关闭时取消 HTTP 上下文、模拟已关闭会话和不可用的观察结果。
终端观察固定到 `/bin/false`，不会访问用户的 tmux 服务。

## Acceptance Evidence

- 使用 Git overlay 将同一组回归用例运行在修改前代码上：断连后的删除、已关闭会话重试、
  关闭前路径检查均失败；断连案例返回 `NOT_GIT_REPO, stage=remove, done=[kill]`。
- 修复后上述回归全部通过。
- 原有 `TestWorktreeSessionLifecycle` 通过，覆盖真实 Git 与隔离 tmux 的创建、派生、
  丢弃删除、合并删除。
- 重复 squash 的旧代码回归返回 `COMMIT_FAILED: nothing to commit, working tree clean`；
  修复后保持同一个合并 OID，关闭接口也能在 squash 已完成、会话已关闭时继续删除。
- 本地验证日志：`/tmp/worktree-cleanup-before.log`、`/tmp/worktree-cleanup-after.log`。
- 最终 `scripts/dev/quality/check.sh quick` 通过，包括全仓库 Go 测试、前端 i18n、hover、
  typecheck 与秘密扫描；未修改前端或 Python，未执行无关的 Python 依赖同步和测试。
- 回归证据截图：`/tmp/worktree-cleanup-evidence.png`；门禁日志：`/tmp/worktree-cleanup-quality.log`。

### CI 身份兜底回归

PR #747 的首次 Quality Gate 在重复 squash 时暴露 `Committer identity unknown`。
本机全局 Git 身份掩盖了这个问题：`git merge --squash` 也会读取提交者身份，
不能只在随后的 commit 上兜底。该调用改用现有 `gitID`，仍优先保留用户已配置的身份。
提交钩子还会只传入作者身份，`gitID` 因此改为分别检查作者与提交者，独立补齐缺失项；
新增回归确认补齐提交者时不会覆盖已知作者。
两项 squash 回归通过 `GIT_CONFIG_GLOBAL=/dev/null`、`GIT_CONFIG_NOSYSTEM=1`
隔离全局和系统 Git 配置；同条件下旧调用失败，修复后通过。

## 本机遗留情况与边界

2026-11-06 只读盘点时，本仓库共注册 60 个 worktree（含主工作区），54 个目录存在，
6 条记录指向已不存在的目录。部分 `/tmp` 工作区用于额外开发验证，
本机脚本中也存在显式 `git worktree add --detach`，不能把所有记录都视为同一次关闭失败。
没有逐次关闭请求的历史回执，不能断言每个遗留目录的具体来源。

这次修复不会自动清除历史遗留，也不保证磁盘错误、权限错误或服务进程退出时完成清理。
客户端断连后流程仍受服务端超时约束；删除失败时继续返回实际失败阶段。
