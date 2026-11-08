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

## Go 指导包与团队记忆

生产中原 Main 的 swarm_memory_read 返回 unavailable，而真实项目文件和摘要均完好。实际 Go CLI 返回 5 个 `skills/<id>/SKILL.md` 和 2 个 `connectors/<source>/SKILL.md`；后者的 ID 为 `connector-<source>`。Python 只接受第一种路径，误将整份记忆和操作回执能力一并判为不可用，继而阻止复盘及记忆写入。这不是缺少记忆文件。

校验器按 Go 的两类坐标分别验证 ID、路径和摘要，保留项目范围、去重与上下文总量限制；普通 Skill 最多 16 个，Connector 最多 32 个，Connector 的原 source ID 允许完整 64 字符。不能以接受 Connector 为由放开任意路径、外部来源或执行权限。写入入口也明确禁止以占位内容探测真实记忆；发现接口缺口应读 schema/帮助。

验收包含普通与 Connector 混合指导包、两类数量边界、长 source ID、错路径/身份/摘要、重复与超大内容。另保留真实 Go CLI 只读响应的失败与修复重放，核对原记忆 SHA 不变；上线后必须由原 Main 获取真实记忆/复盘回执再关闭 #800，不能以隔离读取成功替代。
