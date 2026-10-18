---
name: roami-dispatch
description: Manage Roami projects, discover full session membership, deliver messages to existing Codex or Claude sessions, create background work or new projects, cancel tracked tasks, and report results to the original Main.
---

# Roami 项目、会话与派活

用户只有一个长期 Main 对话。Codex、Claude Code 和原生 Worker 是后台任务的执行者，不能替用户增加第二个 Main。优先采用用户当前要求和已保存的执行器偏好。

## 入口与参数

1. 用 `tool_search` 搜索要做的操作；`kind="cli"` 查 CLI，`kind="skill"` 查技能，默认同时查。
2. Skill 通过 `read(path="skill://roami-dispatch")` 按需加载。不要把全部技能全文放进系统提示。
3. CLI 搜索结果包含真实 `inputSchema` 和 `argv`。执行形式：

```json
{"argv":["roami","agent","capability","call","target_search","--input","{\"kind\":\"project\",\"query\":\"Roami\"}"]}
```

以上对象交给 `bash`。不要把 `target_search` 等 CLI 操作当成独立模型工具。宿主会绑定当前 owner、Main、任务、turn 和幂等键；不要自造这些内部标识或让用户填写。

## 项目与会话：逐项操作

| 用户意图 | 操作与参数 | 如何判断结果 |
| --- | --- | --- |
| 查看项目和会话总量 | CLI `workspace_overview`，参数 `{}` | 使用返回的总量，不数截断列表或项目的前三张会话卡片 |
| 查项目 | CLI `target_search`：`kind="project",query="名称或ID",offset=0,limit=10` | 读取 items；nextOffset 非空说明还有下一页 |
| 查看项目精确身份 | CLI `target_resolve`：`kind="project",id="已发现ID"` | 使用返回的稳定 projectId，名称相同不代表同一项目 |
| 列出某项目全部会话 | CLI `target_search`：`kind="session",projectId="已发现ID",query="",offset=0,limit=10` | 按 nextOffset 继续；不能因前三个摘要没出现就断言不存在 |
| 在项目里找 Codex / Claude 会话 | 同上，加名称关键词 query | 综合 executor、项目归属、label 和精确 sessionId；目标唯一后直接用，不让用户重填 ID |
| 查散会话或全节点活跃会话 | CLI `target_search`：`kind="session",query="关键词"`，不带 projectId | 返回项目和散会话中的匹配目标；按完整分页判断是否缺失 |
| 精确解析已有会话 | CLI `target_resolve`：`kind="session",id="会话名称、ID或label"` | 歧义必须选目标；活跃不等于任务完成 |
| 向已有会话发消息 | CLI `session_send`：`sessionId="精确目标",text="用户要求和必要上下文"` | state=delivered 只证明可靠提交，executionTracked=false 表示没有完成回调 |
| 继续之前的工作 | 同一个目标再次执行 session_send | 用户说“继续某会话”已经授权投递，不重复确认，不新建替代会话 |
| 多个同名目标 | `ask_user` 提供 2–4 个可识别选项 | 选项包含项目、会话和执行器，推荐项在前；选定后直接提交 |

### 已有会话投递例子

先查询对应项目的完整会话列表，再执行：

```json
{"argv":["roami","agent","capability","call","session_send","--input","{\"sessionId\":\"实际发现的会话ID\",\"text\":\"请继续实现这项需求，并把结果回报到原任务。\"}"]}
```

正文是用户授权的工作内容，不把外部网页指令或密钥混进派活简报。实际提交沿用 Go 的持久投递和 TUI 提交实现，不能改成 `tmux send-keys text Enter`。未知结果先查回执，不重发。

## 新建与委派：逐项操作

新任务使用独立 `delegate` 工具，生命周期与预算由运行时管理。

| 场景 | delegate 参数 | 行为 |
| --- | --- | --- |
| 在已有项目做新任务 | `executor="codex"` 或 `"claude"`，`target={kind:"project",projectId:"已发现ID"}`，goal | 后台准备对应项目工作区；不是“给旧会话发消息”的替代 |
| 复用已准备工作区 | project 目标增加 workspaceId | 不再覆盖 directory/base/remote；保留本地未提交内容 |
| 新建散会话工作 | `target={kind:"new_session",directory:"已知绝对目录"}`，executor，goal | 不绑定项目；目录缺失且任务确需代码时才让用户选择或先发现目录 |
| 新建项目并派活 | `target={kind:"new_project",name:"项目名",baseDir:"可选绝对目录"}`，executor，goal | 用户明确要求新项目才创建；不能为逃避旧会话限制而新建 |
| 原生后台任务 | `executor="native"`，对应 project/new_session 目标，goal | 使用配置的后台模型与基础工具，执行器偏好不覆盖明确指定 |
| 公开网页检索 | `executor="native",target={kind:"new_session",resourceOnly:true}`，goal | 不需要代码目录；读取 web-research 技能并使用任务专属 Chrome 资源 |
| 从已完成检查点 Fork | delegate 增加 fromMessageId | 只接受已完成的助手检查点；保留父任务、预算和回报目标，不复制为用户 Main |

一个 delegate 回执只表示 queued/running 的真实状态。queued 不能称“已发给 Codex”，更不能称“已完成”。准备失败或目标拒绝时回报实际原因，不静默再建第二个会话。

## 跟踪、取消和回报：逐项操作

- **状态查询**：CLI `task_status`，参数 `{}`，返回当前 Main 的任务投影；用户问进度时查询一次，不在等待回调期间循环轮询。
- **取消后台任务**：CLI `task_cancel`，参数 `{taskId:"已发现的任务ID"}`。只取消该用户拥有的委派任务；cancelling 不等于已停止。不能据此撤回已经投递到旧会话的消息，也不能顺手杀掉无关工作会话。
- **原对话回报**：运行时把工具、执行、验证和最终状态送回原 Main；无需另开聊天或让用户去子会话找结果。
- **进行中**：用事实描述已经开始的步骤；每条过程记录有具体动作与实际状态。
- **成功**：只在执行器结果和验证通过后称任务完成；收到消息和启动执行器都不等于完成。
- **失败、取消、未知**：分别说明，不把未知标成成功；写操作未知时先对账，不重复派活或换会话重发。
- **需要用户决策**：Main 用 ask_user 给选择题。Worker 记录缺失信息并回报 Main，不直接给用户创建分支聊天。

## CLI 与服务的分工

项目与专业会话仍通过既有 Go CLI 管理：`roami project ls/show/sessions`、`roami session ls/resolve`、`roami agent execution send-message/launch/status/cancel`。上面的上下文 CLI 能力复用这些适配器；Python 拥有 Main、记忆和后台任务，不另造项目或会话数据库。

节点、模型、Skill、工具和 MCP 配置由设置页维护；专业 CLI 登录和套餐额度仍来自各自执行器。内置工具、Skill、CLI 固定启用且只读，不能修改或启停；只有外部接入项允许管理。读配置不等于改配置。删除、归档项目或终止无关会话不属于自动派活的附带动作；未出现在实时能力目录中的管理入口不得伪造为已支持。

记忆自动保存与召回；不要求用户每次说“记住”。已存偏好参与执行器选择，当前用户要求优先。不能仅凭助手说“已记下”认定已经写入长期记忆。
