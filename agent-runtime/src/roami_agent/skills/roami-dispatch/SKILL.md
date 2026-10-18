---
name: roami-dispatch
description: Operate Roami projects, sessions and background agents through its unified CLI; use Chrome for browser interactions, screenshots and recordings; inspect execution, reminders and node capabilities without duplicating the user's Main conversation.
---

# Roami 操作与派活

用户只有一个长期 Main。Codex、Claude Code、原生 Worker 是后台任务执行者；项目会话不是第二个 Main。已有会话继续投递，新任务才委派；当前用户要求优先于已存执行器偏好。先简短回应，再把需要时间的工作交给后台。

## 按需操作手册

通过 `read` 读取下表的 `skill://` 路径，只加载这次工作需要的手册。设置页的 Skill 详情也可直接查看这些手册。

| 任务 | 文档路径 | 内容 |
| --- | --- | --- |
| 项目、已有会话、Codex / Claude 派活 | `skill://roami-dispatch/references/projects-sessions.md` | 完整分页、精确身份、可靠投递、新建项目 / 散任务、Fork、会话归属、窗格与蜂群 |
| 浏览网页、操作页面、截图 / 录屏 / PDF | `skill://roami-dispatch/references/chrome.md` | 任务专属浏览器、用户现有标签、导航、表单、读取、等待、截图参数、录制与动作回执 |
| 后台进度、回报、提醒、人工接管 | `skill://roami-dispatch/references/agent-tasks.md` | task_status / cancel、CLI execution、steer、report / notify、提醒、资源暂停与恢复 |
| 记忆、文件、MCP、HTTP、Computer Use | `skill://roami-dispatch/references/capabilities.md` | 自动记忆、检索与来源、文件 / 产物、动态能力发现、内置只读与外部能力管理 |
| 登录、节点诊断、插件与数据库运维 | `skill://roami-dispatch/references/node-operations.md` | auth、服务状态、插件清单 / 命令、数据库备份、维护边界与失败定位 |

## 入口、权限与真实可用性

- **Main / 原生 Worker 的受管操作**：`tool_search(query="意图或操作名",kind="cli")` 返回真实 `argv`、`inputSchema`、`effect`，交给 `bash` 执行。Skill 用 `kind="skill"` 搜索，再用 `read` 加载。已知且仍有效的命令不必重复搜索。
- **专业 Agent / 普通终端的完整 CLI**：`roami help`、`roami project help`、`roami session help`、`roami agent help`、`roami chrome help`。`chrome` 是 `roami chrome` 的兼容入口。具体 flags 以当前节点帮助为准。
- 两者不是同一个权限范围：当前宿主直接允许的原始 Roami 命令只有项目 ls/show/sessions、会话 ls/resolve 与少量帮助；其他操作使用已注册能力或委派具备 CLI 环境的专业 Agent。**文档列出命令不代表当前角色可以直接执行它**。不能通过 Shell 包装绕过 USE_REGISTERED_CLI_CAPABILITY、资源租约或检索角色限制。
- 已有项目和会话使用 Go 台账；Main、记忆、任务生命周期使用 Python 服务。不要另建数据库或手写 HTTP 替代现有 CLI。

执行受管能力的例子（JSON 对象交给 `bash`）：

```json
{"argv":["roami","agent","capability","call","target_search","--input","{\"kind\":\"project\",\"query\":\"Roami\"}"]}
```

宿主绑定 owner、Main、task、turn 和幂等键；不要自造、向用户索取或从旧日志复制这些内部标识。CLI 回执为事实依据，非零退出、failed、unknown 分别如实显示；未知写结果先查回执，不重发。

## 决策与回报

- “给这个 Codex 会话发消息 / 继续”已授权投递；查到唯一目标直接执行 `session_send`，不要再次确认、让用户粘贴命令或另建项目。多个目标才用 `ask_user` 给 2–4 个可识别选项。
- 查项目总量用 `workspace_overview`；查某项目会话用 `target_search(kind="session",projectId=...)` 并跟随 `nextOffset`，不能把前三张卡片当全部。
- 新项目、散任务和新项目工作区用 `delegate`；网页查询用原生 `resourceOnly` 检索任务，不创建代码项目。完整网页交互与纯公开检索的角色不同，见 Chrome 手册。
- `delivered` 只代表消息已提交；`queued` 只代表任务入队；只有执行与验证通过才说完成。没有生命周期回调的旧会话会返回 `executionTracked=false`，不能声称会自动拿到完成结果。
- 工具动作和结果回到原 Main；用户不必打开分支聊天。Worker 缺信息时回报 Main，Main 必要时提供选择题。
- 内置工具、Skill、CLI 固定启用且只读，不能修改或启停；只有外部接入项允许管理。系统插件是另一类节点资源，不把“插件可配置”误当成内置 Agent 能力可以禁用。
- 自动记忆与召回无需用户每次提醒；明确“记住”的偏好应有落库来源，不能仅凭助手自述说已保存。当前请求仍然优先。
