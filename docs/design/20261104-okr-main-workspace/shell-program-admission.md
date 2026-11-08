# Shell 程序的工具准入

## Product Design

原数据成员已取得成片 ASR，后续字幕比对的有效 Python heredoc 却被执行前拒绝。完整 shell 程序不能按 CLI 参数解析；用户应得到真实运行结果，语法错误也应保留 bash 的退出码与诊断。关联 #817。

## User Stories

- Main 与原成员在绑定工作区运行 Python heredoc，正文引号不触发无关的参数校验错误。
- 已注册 CLI 继续通过当前权限与上下文调用，包装调用仍拒绝，不从脚本文本借用身份。

## Technical Design

`ToolDirectory.argv` 只读取首词用于分类。普通 shell 程序交既有 shell handler 原样执行，保留角色、目录、超时与环境限制；首词是已知 Roami CLI 时才完整解析参数。显式 argv 不变。既有 wrapped_command 恢复提示继续拒绝受管 CLI 的命令链、管道和包装；它不是任意 shell 的安全解析器。heredoc 数据不作为注册能力调用。

## Acceptance

实际失败命令仅用 bash -n 核验为有效语法，未重复执行生产命令。隔离回归覆盖两种角色的真实 Python heredoc 输出、原生 bash 语法失败回执，并复用受管包装拒绝、命令发现和绑定回归。尚未合入部署；最终需原团队后续实际运行证据。
