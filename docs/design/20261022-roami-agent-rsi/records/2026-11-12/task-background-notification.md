# 后台通知不改变委派任务绑定

## Product Design

Claude 的后台工具完成通知也可能经过 UserPromptSubmit。宿主应保留原任务身份，等真正的 Stop、空后台任务/定时器注册表及匹配 idle 通知确认结束。后台通知自身不表示任务完成，文件与执行器的完成声明也不提供停止证明。

## User Stories

- 后台等待结束后，原任务能继续执行并正常收尾，不因内部通知进入“执行待确认”。
- 用户追加请求、定时触发或其他来源的消息仍触发原有输入绑定检查。
- 未结束的工具继续保留，失败回调仍须完成工具配对。

## Technical Design

`session-claude-notification.go` 在输入绑定变更前只读校验提供方历史：当前受管 Claude 必须 busy，provider、prompt ID 与原轮次一致；原输入内容摘要与工作目录匹配。通知必须逐字匹配原生 queued_command，且 commandMode 为 task-notification，origin 为 task-notification / session-task，无其他 subkind。原输入之后出现普通用户文本、其他来源的排队指令或侧链则拒绝豁免。

沿用受保护 transcript 的路径、唯一 provider、属主、权限、大小限制，并核对读取前后的文件身份、长度和修改时间。验证通过时保留原输入绑定和工具集合，作废可能过期的 Stop 候选；其余消息走原有检查，不恢复 unknown 或清除 workspace fence。正常完成仍使用现有 Stop 和 idle 协议。

## 验收

- 修复前覆盖测试复现 `SESSION_PROMPT_MISMATCH`；修复后同一用例保持 running，配对失败工具回调后经 Stop 与 idle 正常 succeeded。Stop 后再来的通知会作废旧候选，不能凭后续 idle 提前完成。
- 专项测试覆盖 21 个通知来源/绑定/文件场景及一次完整任务收尾，包含重复通知、历史对话、用户复制通知、排队用户请求、定时触发、侧链、错误 provider/turn/摘要/目录、不可信文件及 unknown 生命周期。
- 对现场原生历史只读调用实际识别函数，4 条后台通知均能识别。现场状态文件保持原样，未重发输入、调用模型、重跑调研或修改任务数据库。
- `go test ./internal/agentexecution ./internal/agentlifecycle ./cmd/roami -count=1` 与最终 `scripts/dev/quality/check.sh quick` 通过；后者包含全部 Go 测试、i18n、hover、TypeScript 与代码扫描。没有修改 Python 或前端代码，按差异范围跳过 Python 套件。
- 历史任务已经处于 unknown，且有旧版失败工具回调残留。本改动防止正常新轮次被通知破坏；不据已有文件和最后一段回答追认历史任务完成。部署与历史任务的可信对账分别验收。
