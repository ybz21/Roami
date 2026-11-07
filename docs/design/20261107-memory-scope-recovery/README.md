# 会话内存误杀排查与恢复

## Product Design

内存测试不得改变开发会话或 tmux server 的内存上限。只有确认 pane 已进入独立的
`tmux-spawn-*.scope` 后才能设置硬限和软限；隔离未完成时等待重试，无法确认则返回错误。

恢复会话沿用原工作目录和已核对的 Codex 对话 ID。恢复的是终端入口与对话记录，
被终止的进程无法原地恢复。

## User Stories

- 开发者使用 128MiB 限额验证内存保护时，当前工作会话与测试服务器继续运行。
- pane 还在父进程的 scope 内时，不给父 scope 设置测试限额。
- 会话消失后，能够找到原工作树、未提交修改和原对话，并区分进程退出与目录删除。

## Technical Design

### 已核对的退出原因

| 时间（2026-11-07，Asia/Shanghai） | 会话 | 证据与结论 |
| --- | --- | --- |
| 08:09:07 | `2026-1107-0003-00h8`，会话内存保护 | `systemd-oomd` 终止 `tmux-spawn-5086dcab-8957-4871-8809-c2a0eff87f65.scope` 中的 11 个进程。用户服务内存压力持续超过 20 秒，达到 55.11%，阈值为 50%。被选 scope 当时占用 391.1MiB，压力 Avg10 为 60.24%；台账记录峰值 876236800 字节。该次不是单会话撞硬上限。 |
| 16:47:25 | `2026-1107-1614-00ie`，内存冻结查找 | 内核调用栈包含 `memory_max_write`。`tmux-spawn-02c13041-d000-4d19-bb1f-f165afa86437.scope` 的硬限被设为 131072KiB，当时用量 445136KiB。Codex、Node、测试服务和 shell 随后被 cgroup OOM 终止。原对话最后一个命令正在以 `ROAM_SESSION_MEM_MAX=128M` 创建测试会话。 |

08:09 的全局压力另有原对话记录：多个 OKR 完整测试把临时目录放进 `/dev/shm`，
当时占用约 14.4GiB，8GiB 磁盘交换区接近用满。原会话已在中断前迁移其中一批目录。
这说明不能仅凭当前 Agent 的 RSS 判断是否会被 oomd 选中；不能据此断言 Agent 有堆泄漏。

16:47 的测试使用了私有 tmux socket，但私有 server 继承了调用者的 cgroup。
OOM 进程列表同时包含工作 Codex、测试 tmux server（PID 2879398）和测试服务。
原 `Apply` 只检查 scope 名以 `.scope` 结尾，未确认其与控制进程、pane 父进程隔离。
pane 迁移未完成或失败时，继承的工作 scope 因而会被误认为测试 pane 的 scope。
现有日志不能进一步区分当次迁移是延迟还是失败。

### 代码与模块

- `internal/memguard/pane-scope.go`：读取 pane、控制进程和 pane 父进程的 cgroup；
  只允许独立的 `tmux-spawn-*.scope`。拒绝控制进程/父进程所在 scope 及其祖先，
  缺少隔离证据也拒绝。
- `internal/memguard/memguard.go`：`Apply` 和 `SetHigh` 每次写入前使用同一检查。
  保留现有 2 秒重试与内核回读确认，以便 pane 迁移完成后正常设置限额。
- `internal/memguard/pane-scope_test.go`：覆盖控制进程、父进程、嵌套 cgroup、未知路径和
  正常独立 pane。用替身 `systemctl` 验证对自身设硬限和软限均不会执行写入命令。

### 恢复结果

- 功能工作树：`.worktrees/2026-1107-0003-00h8`，分支 `feat/session-memory-pause`。
  34 个已暂存修改文件仍在（837 行新增、66 行删除），目录没有被删除。
- 原功能入口恢复为 `2026-1107-1659-00ip`，名称“会话内存保护”，关联原 Codex 对话
  `01a1b199-fee8-7bb2-ac6e-d6cec74ac054`。
- 最近查找入口恢复为 `2026-1107-1701-00iq`，名称“内存冻结查找”，关联原 Codex 对话
  `01a1b512-d5d9-72c3-8231-206ac254f0d8`。
- 两个入口的恢复命令均已预填；由用户回车接回原对话。
- 原功能补丁与现场日志另保存在 `/tmp/roami-memory-recovery-20261107/`，不提交一次性产物。

## Acceptance Evidence

- `scripts/dev/quality/check.sh quick` 通过，包括全量 Go 测试、前端静态检查和提交策略检查。
- `go test ./internal/memguard ./internal/memthrottle ./internal/tmuxruntime ./internal/session` 通过。
- `go test ./internal/memguard -run 'TestMemory' -v` 通过；自身硬限/软限测试确认没有调用
  `systemctl` 写入，测试替身不会改动真实 cgroup。
- 构建修复后的 CLI，在 `scripts/dev/isolated-roami.sh` 记录的私有实例中连续创建并关闭
  4 个 128MiB 测试会话：4 个 pane 均进入不同的独立 scope，`memory.max` 均回读为
  134217728；工作会话前后均为 13304680448，测试 server 保持存活。
  结果保存在 `/tmp/roami-memory-recovery-20261107/scope-regression.json`。
- 本次只修复限额写入的隔离检查。原告警与冻结功能仍是原工作树内的未提交工作，
  本次提交不代表该功能已经发布；运行中的 Roami 也未被替换。
