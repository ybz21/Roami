---
name: roami-session
description: 管理 Roami 的持久会话、派生派活、会话通信和 swarm 蜂群：创建成员、看板分工、消息协作、巡检与完成状态。用于会话 CLI 操作，不替代项目开发流程。
allowed-tools:
  - Bash(roami session *)
  - Bash(roami swarm *)
  - Read
---

# Roami 会话

使用 `roami session help` 查询本节点支持的命令。蜂群入口为 `roami swarm`，`roami swarm help` 和蜂群子命令 `--help` 只显示帮助；其他能力仍先查其帮助。`roami session swarm` 使用同一实现。

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

蜂群绑定现有 Roami Main。使用 `cc-swarm` skill 了解受管任务编排，使用 `dev-roles` 定义角色范围与验收。当前 CLI 不启动额外指挥，也不接受旧的 add/adopt/done/activate、卡片流转或广场监听命令。

```bash
roami swarm new <名称> --key <持久请求键> --goal "目标与验收标准" [--main-conversation <对话ID>] [--dir <目录>]
roami swarm ls
roami swarm status <sw-id>
roami swarm board <sw-id>
roami swarm chat <sw-id> --follow
roami swarm members <sw-id>
roami swarm work <sw-id> <成员名或工作项ID>
roami swarm collect <sw-id>
roami swarm plan <sw-id> --file plan.json
roami swarm dependencies <sw-id> --file dependencies.json
roami swarm pause <sw-id> --key pause-1 --revision N
roami swarm resume <sw-id> --key resume-1 --revision N
roami swarm stop <sw-id> --key stop-1 --revision N
roami swarm archive <sw-id> --key archive-1 --revision N
roami swarm say <sw-id> "补充需求" --key message-1
roami swarm say <sw-id> "继续修改" --to api --task-revision N --key revise-1
roami swarm member add <sw-id> api --executor codex --goal "实现接口" --acceptance "接口测试通过" --key member-1 --revision N
```

`new` 缺省复用节点 Main，也可明确指定现有普通 Main 对话。`--json` 提供结构化结果，`chat/board/status --follow` 通过 SSE 订阅并退避重连，Ctrl-C 退出。`--file -` 可从 stdin 读取批量计划等完整 JSON 请求。请求文件使用 `commandKey` 持久幂等键，计划/依赖/控制还带 `expectedRevision`。成员在计划中指定 executor、goal、acceptance 与 dependencies，实际派发走 Tasks。指定上游版本通过独立验收后才解锁下游；最终整合项覆盖全部工作后整群才完成。

用户发给 Main 的群聊进入绑定对话；指定成员时续派原任务。专业执行器使用任务提示中提供的 taskId/runId/taskRevision，执行 `swarm post <sw-id> --file message.json` 回传讨论。普通会话的 send 与专业任务派发仍是不同操作。

## 生命周期与隔离

公共 CLI 不提供原生 tmux 命令透传或全局关闭入口。测试只在记录了独立 socket 的实例里执行：使用仓库 `scripts/dev/isolated-roami.sh <测试目录> <命令...>` 启动，使用同一入口的 `--stop` 清理。不要用当前终端继承的 socket 清理测试，也不要只改 `TMUX_TMPDIR` 后执行全局停止命令。

旧终端日志可能包含敏感内容，按任务需要读取；当前日志位于配置的数据根下的 `logs/<会话ID>.log`，默认是 `~/.roami/logs/`。恢复时根据原对话记录选择 Codex、Claude、OpenCode 等执行器，不能用新对话冒充原现场。
