# 项目、会话与可靠派活

下文命令后的对象表示 `--input JSON` 的输入；原生任务执行完整 argv，身份由宿主绑定。

## 项目与会话：逐项操作

以下操作名是受管 CLI 能力，使用 命令族帮助返回的真实命令及 `--input JSON` 的搜索结果 argv，由 `bash` 执行；不是新增的模型工具。

| 意图 | 操作 / 参数 | 结果判断 |
| --- | --- | --- |
| 统计当前节点 | `roami project overview {}` | 直接用返回总数，不数摘要卡片 |
| 查项目 | `roami agent target search {kind:"project",query:"名称或ID",offset:0,limit:10}` | 有 nextOffset 继续分页，最大 limit 以 schema 为准 |
| 解析项目 | `roami agent target resolve {kind:"project",id:"发现的ID"}` | 使用稳定 projectId，不凭同名猜测 |
| 项目完整会话 | `roami agent target search {kind:"session",projectId:"发现的ID",query:"",offset:0,limit:10}` | nextOffset 为空才结束；摘要前三条不代表全部 |
| 在项目找 Codex / Claude | 同上，加 query 名称关键词 | 同时核对 executor、项目、label、sessionId；不是只按显示名 |
| 散会话 / 全节点查找 | `roami agent target search {kind:"session",query:"关键词"}`，不带 projectId | 保留项目归属，逐页判断目标是否缺失 |
| 严格解析会话 | `roami agent target resolve {kind:"session",id:"名称、ID或label"}` | 歧义用选择题，不自动选第一个 |
| 给已有会话发消息 / 继续 | `roami session send {sessionId:"精确目标",text:"用户交办内容"}` | delivered 是提交成功；replyExpected / dispatchId 关联 CLI 回报，executionTracked=false 表示无供应商生命周期证明 |

先查询完整目标，再可靠投递：

```json
{"argv":["roami","session","send","--input","{\"sessionId\":\"实际发现的ID\",\"text\":\"请继续完成用户交办的需求，并说明验证结果。\"}"]}
```

复用现有持久投递与 TUI 提交路径。不能用 `tmux send-keys text Enter` 替代；目标名在 tmux 中是前缀匹配，底层必须使用精确身份。未知提交结果先对账，同一意图不换新幂等键盲目重发。用户明确指定投递已经授权，不重复确认。

## 新建项目、散任务和 Fork

使用模型的 `delegate`，不是把新会话命令拼进旧会话投递。

每次 `delegate` 都带 `routing:{complexity:"bounded",complexityBasis:{维度:"具体事实"},routingExplanation:"本次执行负担",explicitExecutor:null}`；复杂工作把 complexity 改为 `complex`。用户指定执行器时，把 `explicitExecutor` 改成 `native` / `codex` / `claude` / `opencode` / `pi`，同时提供原始用户消息中的准确 `userQuote`；没有指定则用 `null` 并省略 `userQuote`。选择不能只写进 goal、说明或引文，不再填写顶层 executor。依据实际自主探索与验证负担判断复杂度，不按文件类型或任务名称分流。

| 场景 | 参数 | 行为 |
| --- | --- | --- |
| 项目新任务 | `target:{kind:"project",projectId:ID}`, goal, routing | 复杂任务选择可用专业执行器；后台准备项目工作区 |
| 复用工作区 | 上述 target 增加 workspaceId | 不覆盖 directory/base/remote，不 fetch/reset 本地改动 |
| 新散任务 | `target:{kind:"new_session",directory:"已知绝对目录"}`, goal, routing | 不绑项目；需要文件时必须使用正确的本机目录 |
| 新项目 | `target:{kind:"new_project",name:"名称",baseDir:"可选父目录"}`, goal, routing | 仅在用户要求新项目时创建，不用于逃避旧会话限制 |
| 原生 Worker | bounded routing，合法 project/new_session 目标，goal | 用后台模型执行，显式指定优先于历史偏好 |
| 简单公开网页研究 | `target:{kind:"new_session",resourceOnly:true}`, goal, bounded routing | 无代码目录，沿用已启用的 Skill、MCP、CLI 和浏览器能力 |
| 检查点 Fork | delegate 增加 fromMessageId | 只从已完成助手检查点派生；保留父任务、预算和原 Main 回报目标 |

queued / preparing 不代表已给 Codex 投递，失败不静默创建第二个会话。专业 Agent 是否安装、可登录、用量可读是不同状态，不能把未知额度说成额度充足。

目录被拒后停止本轮委派，向用户说明并等待正确目录，不删除目录参数或改目标绕过。指定执行器不可用时说明或询问，不更换执行器或去同项目的其他会话投递。

用户没有说明是否写文件时，按实际场景确定交付：简单、有界工作（如问答、天气查询、简短整理）默认在聊天回复，不额外生成文件；复杂调研、方案、原型等默认将合适的成果保存为文件。用户要求修改的代码或其他文件本身就算文件交付，不强制再写一份报告。把交付要求明确传入 delegate 的 goal，复杂任务保存后回读核验并返回真实文件链接。用户要求优先：简单任务明确要文件就保存，复杂任务明确只在聊天回复、禁止写文件就不落盘，仍按复杂度使用专业执行器。文件保存在已绑定且核实的工作区；目录未知时发现或询问，不编造路径、不为普通文件交付新建无关项目。

## 完整 Go CLI：供专业 Agent / 终端使用

```bash
roami project ls --json
roami project show PROJECT_ID --json
roami project sessions PROJECT_ID --json
roami project activity PROJECT_ID --json
roami project create /absolute/repository --name "显示名" --json
roami project prefs PROJECT_ID --name "新显示名" --pinned true --agent codex --base main --json
roami session ls --live --json
roami session ls --tree --json
roami session resolve "目标" --strict --json
roami session children "父会话" --json
roami session rename "旧名称" "新名称"
roami session fork "父会话" "子会话" --dir /absolute/workspace --detach --json
```

项目 create 可用 `--clone URL`，受管新项目供给还使用 `--provision-key KEY --base-dir DIR`，由宿主产生幂等键。`project remove PROJECT_ID` 删除的是项目登记，不得推断为删磁盘仓库；操作前以节点帮助及用户范围为准。

会话其他命令：`new [名称]`、`a [名称]` 附加、`d [名称]` 分离、`kill [名称] [--cascade]`、`parent set 子 父 / clear 子 / get 子`；`nw/lw/kw` 管窗口，`sp [-h|-v]/kp` 管窗格。附加是交互操作，不在无人值守工具调用里阻塞等待。关闭 / 级联关闭不属于一般派活的附带动作，不用 killall 清理任务。

## 蜂群与环境

`roami session help` 查看蜂群命令索引；`roami session swarm ls --json` 列出蜂群。swarm 没有 help 子命令，不猜用法。支持 new/add/ls/status/activate/done/adopt/archive/rm、say/feed/listen/watch、board/task/sql。先区分查看看板、向群发言和创建多人执行任务；用户仅问进度时不启动新蜂群，也不把 Main Fork 当成 tmux session fork。

`roami session env set KEY=VALUE / rm KEY / clear / push` 修改后续会话环境；`info` 查看服务器、环境或归属修改仅在任务确实要求时执行，不从对话正文复制密钥到全局环境。`roami session` 拒绝未知命令，不透传 tmux；拼写不确定时先读帮助。
