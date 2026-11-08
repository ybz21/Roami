# 受管命令与普通 Shell 的边界

## Product Design

Main 将 `roami agent task status` 包进 `cd … && … | head` 后，命令落入普通 Shell，原生 CLI 因缺少真实 turn/call 而拒绝。当前恢复提示只覆盖已经进入注册解析的错误，未覆盖这个入口。应在执行前指出必须单独调用，并给出当前角色可用的准确命令及 schema；不代填身份、不拆开执行用户的复合命令。

## User Stories

- Main 用原绑定上下文调用任务、群聊、记忆等注册能力，不需要猜 turn/call。
- 复合命令在 Shell 和业务操作执行之前拒绝，修正后由原 Main 正常调用。
- 普通开发 Shell、命令示例文本和成员已有的原生 Chrome/ADB 路径保持可用。

## Technical Design

在 ToolDirectory 中识别 Shell 命令位置上的已注册入口：管道、链接、换行、重定向及常用 env/command/exec 和 shell -c 包装。只提供错误和重试指引，不提取并执行子命令。保留原注册解析、角色/当前回合 admission、schema 校验与真实 binding。目录提示仅返回当前角色可用的能力。

这不是通用 Shell 安全沙箱；现有 Shell 权限和执行隔离仍是边界。独立受管命令的 JSON 字符串可以包含管道、分号和命令示例，不能据其内容误拒绝。普通 Shell 中的 echo/printf 等引用文档也不能误判为命令执行。含 heredoc 的复杂脚本保留原 Shell 路由，不将其中的文档正文当命令；本次只对可识别的常用包装提供执行前恢复提示，不声称覆盖任意 Shell 语法。

## Acceptance

用真实 Runtime 调用证明：包裹命令不启动 Shell/业务 handler；同一原 Main 的单独命令到达 handler 且保留真实 binding；禁用/角色限制仍生效。验证 JSON/引用文本与普通 Shell、已有原生工作流不被误拦。将实际排障经验写入完整初始化模板和运行手册，不把工具目录等同于成员机器能力，也不把群聊投递等同于完成。
