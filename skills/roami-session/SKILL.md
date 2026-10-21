---
name: roami-session
description: 管理 Roami 的持久会话和蜂群：查询、创建、派生、发送输入、读取终端和按明确目标关闭会话。用于需要会话 CLI 的任务，不替代项目开发流程。
allowed-tools:
  - Bash(roami session *)
  - Read
---

# Roami 会话

使用 `roami session help` 查询本节点支持的命令。会话 ID 是稳定身份，label 只是可重复的展示名；自动化先用 `roami session resolve <目标> --strict --json` 解析，再保存返回的 ID。

```bash
roami session ls --json
roami session ls --tree --json
roami session new build-check --dir /path/to/project --detach --json
roami session fork <父会话ID> review --dir /path/to/worktree --detach --json
roami session capture <会话ID> --lines 100
roami session keys <会话ID> Down Enter
roami session send <会话ID> "需要提交的输入"
roami session rename <会话ID> "新名称"
roami session kill <会话ID> --yes
```

`send` 使用粘贴缓冲和独立 Enter 提交，适用于多行输入和智能体 TUI。会话 ID、目录和执行器要以实际查询结果为准；看不到会话时先检查观察错误，不据此清理资源。

需要用户授权的并行协作时使用 `roami session swarm help` 查询蜂群命令。普通会话的创建与发送输入、专业智能体的任务派发是不同操作；需要专业任务的结果和验收时使用 `roami agent execution`，不要把命令投递成功当成任务完成。

公共 CLI 不提供原生 tmux 命令透传或全局关闭入口。测试只在记录了独立 socket 的实例里执行：使用仓库 `scripts/dev/isolated-roami.sh <测试目录> <命令...>` 启动，使用同一入口的 `--stop` 清理。不要用当前终端继承的 socket 清理测试，也不要只改 `TMUX_TMPDIR` 后执行全局停止命令。

旧终端日志可能包含敏感内容，按任务需要读取；当前日志位于配置的数据根下的 `logs/<会话ID>.log`，默认是 `~/.roami/logs/`。恢复时根据原对话记录选择 Codex、Claude、OpenCode 等执行器，不能用新对话冒充原现场。
