---
name: roami-session
description: 管理 Roami 的持久会话、派生派活、会话通信和 swarm 蜂群：创建成员、看板分工、消息协作、巡检与完成状态。用于会话 CLI 操作，不替代项目开发流程。
allowed-tools:
  - Bash(roami session *)
  - Read
---

# Roami 会话

使用 `roami session help` 查询本节点支持的命令。当前 CLI 没有 `swarm help`；子命令不统一支持 `--help`，不要把它当作无副作用的探测方式。

会话 ID 是稳定身份，label 只是可重复的展示名；自动化先用 `roami session resolve <目标> --strict --json` 解析，再保存返回的 ID。

## 会话与派活

```bash
roami session ls --json
roami session ls --tree --json
roami session new build-check --dir /path/to/project --detach --json
roami session fork <父会话ID> review --dir /path/to/worktree --detach --json
roami session children <父会话ID> --json
roami session capture <会话ID> --lines 100
roami session keys <会话ID> Down Enter
roami session send <会话ID> "需要提交的输入"
roami session rename <会话ID> "新名称"
roami session kill <会话ID> --yes
```

`new` / `fork --json` 返回的 `session` 字段是新会话 ID。`fork` 继承工作目录和环境、记录父子关系，不会复制 Agent 对话、启动 Agent 或创建 Git worktree。并行改代码时按项目约定准备工作目录。

派活前先 `capture` 确认目标正在运行什么。新会话是 shell，需发送已安装 Agent 的启动命令与起步任务；已有 Agent 会话可直接接收后续任务。不要把自然语言任务发给 shell 当作命令执行。

`send` 使用粘贴缓冲和独立 Enter 提交，适用于多行输入和智能体 TUI。发送成功只证明输入已提交；之后读取进展，处理阻塞，核对产物与测试再报告完成。会话 ID、目录和执行器要以实际查询结果为准；看不到会话时先检查观察错误，不据此清理资源。

## 蜂群分工与沟通

按任务范围和项目规则选择并行方式，已有授权不重复询问。需要完整拆任务、巡检与集成流程时按需读同目录的 `cc-swarm` skill；需要角色职责划分时读 `dev-roles` skill。

当前会话自己指挥时，用 `--no-master` 避免额外启动指挥 Agent。省略该参数会尝试启动 Claude 指挥会话。成员的 `--kind` 要选择本机已安装可用的类型；显式 `--role member` 避免首个成员被当成指挥。

```bash
roami session swarm new <群> --goal "目标与验收标准" --no-master
roami session swarm add <群> <成员> --type agent --kind codex --role member --dir /path/to/worktree "任务与验收标准"
roami session swarm status <群> --json
roami session swarm collect <群> --json
roami session swarm task add <群> "任务标题" --desc "范围与验收标准" --assignee <成员>
roami session swarm task assign <群> <卡ID> <成员>
roami session swarm task ls <群> --assignee <成员> --json
roami session swarm task show <群> <卡ID>
roami session swarm task move <群> <卡ID> doing
roami session swarm board <群> --json
roami session swarm say <群> --as <成员> --kind note "进展或接口约定"
roami session swarm say <群> --to <成员> --kind ask "需要确认的问题"
roami session swarm feed <群> --json
roami session swarm listen <群> --as <成员> --mentions --once
roami session swarm task done <群> <卡ID>
roami session swarm done <群> <成员>
roami session swarm done <群>
```

`--type agent` 的内容是给 Agent 的任务，`--type task` 的内容是 shell 命令。`swarm say --to` 将消息写入广场，不能替代 `session send` 向终端提交输入；巡检时读 `feed` / `listen`，需要直接续派任务时用会话 ID 发送。

任务卡状态、成员完成状态与实际产物需分别核对。成员成果通过验收后再标记卡片和成员完成，最后做整体验收。`swarm add --depends-on` 记录软依赖，不阻止新成员启动；需要等上游时先验收上游再派下游。`swarm activate <群> [成员]` 用于解锁已有挂起成员。

普通会话的创建与发送输入、专业智能体的任务派发是不同操作；需要专业任务的结果和验收时使用 `roami agent execution`，不要把命令投递成功当成任务完成。

## 生命周期与隔离

公共 CLI 不提供原生 tmux 命令透传或全局关闭入口。测试只在记录了独立 socket 的实例里执行：使用仓库 `scripts/dev/isolated-roami.sh <测试目录> <命令...>` 启动，使用同一入口的 `--stop` 清理。不要用当前终端继承的 socket 清理测试，也不要只改 `TMUX_TMPDIR` 后执行全局停止命令。

旧终端日志可能包含敏感内容，按任务需要读取；当前日志位于配置的数据根下的 `logs/<会话ID>.log`，默认是 `~/.roami/logs/`。恢复时根据原对话记录选择 Codex、Claude、OpenCode 等执行器，不能用新对话冒充原现场。
