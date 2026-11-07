# 原生成员的旧 CLI 入口

## 问题与用户故事

原 Main 应把明确的分工交给原成员，成员完成工作并回报；成员不能无意间成为另一个用户，给自己续派或重新唤醒 Main。

真实每日采集复现了两个相关问题：旧 runtime 把用户给 Main 的整段协调指令当作成员执行正文，成员误认角色；随后成员从 shell 调用旧 `roami agent steer`，该入口按外部用户写入，丢失原 turn/tool 身份，造成自我续派且没有取数。前一问题的 Main 分工/原用户来源分离已有合入修复，但尚未激活；本轮收紧后一入口。真实项目身份及原始文本保存在私有验收记录，不放进公共设计。

## 行为与实现

`cmd/roami/agent.go` 在解析参数后、解析存储位置及读取消息输入前检查原生工具上下文。出现 caller role、turn ID、tool call ID 任一标记时，旧 `new/send/notify/steer` 返回 `USE_REGISTERED_CLI_CAPABILITY`，不发送 owner/user 写请求。明确的外部用户 CLI 继续原行为。

Main 与成员都使用已注册 CLI 能力，由活跃 tool context 验证参数、来源与执行范围。`agent capability` 和命名命令族维持原准入路径。外部定时器使用 project-scoped `wake`；它拒绝原生上下文，补上仅有 tool call ID 时的检查。报告回执、只读历史、身份恢复等入口不扩大限制。

这是避免身份丢失的调用契约，不是同一 Unix 用户任意 shell 的安全隔离。禁止通过清理环境变量教成员回落外部用户入口，也不把此修复单独当成自动协作或每日调度已完成。

## 验收

修复前，四种旧写操作乘六种完整/部分原生身份共 24 个用例都实际到达私有测试服务；修复后必须全部拒绝且无 HTTP 写请求。四种普通外部操作继续保留目标、文字、换行与 revision。外部 wake 保留原文与项目范围；三种单独的原生身份标记均不得到达 wake，已注册命令族继续通过原能力入口。

测试使用私有临时 SQLite 与 Unix socket、真实 CLI 子进程，无模型、真实 Agent 或生产 tmux。相关专项及仓库 full 已通过，Go 全量通过；按照真实差异跳过 Python pytest 与 Skill 全套，前端门禁/生产 build 通过。正常提交 quick 和 CLI 截图记录在本次交付日志；线上激活与 Main 正常转交仍分别验收，#720/#744 保持开放。
