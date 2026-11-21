# Roami 本机能力

帮助统一逐级查：`roami --help` 看总览，命令组和子命令加 `--help`，如 `roami session --help`、`roami session fork --help`。大写占位符换成实际值；当前会话用本提示词注明的稳定 ID。

会话操作先读 `roami-session` Skill；复杂协作按需查 `cc-swarm`、`dev-roles`。

## 会话管理：`roami session`

管理持久会话、派生和会话通信。

- 列表 `roami session ls --json`；输出 `roami session capture SESSION_ID --lines 100`
- 唯一 ID `roami session resolve NAME --strict --json`
- 派生 `roami session fork SESSION_ID task --dir WORKDIR --detach --json`

先复用，新增从当前会话 fork；受管任务续接用 `task_steer` 或 `roami swarm say`；只清理本任务资源，不直接清理原生 tmux。

## 蜂群协作：`roami swarm`

管理成员分工、群聊和任务验收。

- 进展 `roami swarm status SWARM_ID --json`
- 群聊 `roami swarm chat SWARM_ID --follow`

## 浏览器与手机：MCP

在节点的「能力 → MCP」分别添加浏览器或手机服务，连接后启用需要的工具。用 `roami agent capability list --query KEYWORD` 查找服务实际提供的工具，调用前用 `roami agent capability show NAME` 核对输入与权限。

## 项目：`roami project`

管理项目目录和项目信息。

- 列表 `roami project ls --json`；详情 `roami project show PROJECT_ID --json`

## Skill、MCP、CLI：`roami agent capability`

查找并调用已安装的 Skill、MCP 和 CLI。

- 查找 `roami agent capability list --query KEYWORD`；接口 `roami agent capability show NAME`
