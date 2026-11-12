# 提示词覆盖与精简核对

已按原有“新建任务”和“派生任务”两条链路核对。必要动作已保留或补齐；重复教程、逐项帮助与宿主管理的完整绑定 JSON 不再放进正文。

基线：Git `29ad2179d076ce5cb1237c93f574a3598fb36776`。两类入口分别使用相同任务正文和参数进行新旧对比；普通目录与新建 worktree 单独计量。长度含空格与换行，是字符数，不是模型 token 数。

## 长度

| 样例 | 原版 | 最终版 | 判断 |
| --- | ---: | ---: | --- |
| 新建 worktree | 6375 | 2384 | 减少 62.6%，保留分支与会话改名 |
| 新建普通目录 | 6226 | 2252 | 保留非 Git 目录规则，不误要求改分支 |
| 派生普通任务 | 2347 | 3165 | 增加开工命名、当前会话、具体回报方法与六类能力；不能声称它比最早版更短 |

最终能力说明 1323 字符，通用执行/产物/四项回报约定 631 字符，各注入一次。普通任务不重复注入完整 task/run/Main ID；需要 Agent 发起蜂群消息时，保留真实协议绑定。附件、路由和授权资料按需附加，不计作可任意删掉的模板文字。

## 要点覆盖

| 要点 | 最终处理 |
| --- | --- |
| 任务原文、Markdown、续接 | 原文置顶；续接只带新增要求，保留原授权与已有成果 |
| 四类新建工作区 | 新 worktree 改占位分支；主仓库开任务分支；已有分支不改名、不自动 rebase/reset；普通非 Git 目录不因开工而初始化 |
| 派生任务开工 | 新 Git 项目明确 `git branch -m`；复用分支不改名；检查改动和依赖；续接保留分支与会话名 |
| Roami 展示名 | 新建会话明确 `roami session rename`，指侧栏/筛选中的展示名；不改变稳定 session ID |
| 当前身份 | 宿主注入实际 session ID；执行标签显示 8 位，完整内部绑定和旧提示词哈希保留 |
| 权限、偏好与互审 | 新建 Auto 默认和用户明确权限配置沿用原启动参数；已有会话不重置模型或权限，空闲互审开关与提示保留 |
| 能力发现 | 六组各一句用途和基本命令；总/分组/子命令帮助只在开头说明一次 |
| Skill / MCP / CLI | 保留 Skill 入口、目录名称和 inputSchema、MCP 发现、私有上下文、请求 ID 与未知结果不换 ID 重放 |
| 会话与隔离 | 优先复用、当前会话 fork、唯一 ID 严格解析；受管任务用 task_steer/swarm say 续接；只清本任务资源，Roami 测试用隔离入口和同入口 --stop |
| fork 的边界 | fork 不复制对话、不启动 Agent、不建 worktree，说明放入实际 `roami session fork --help` |
| 回报格式 | 四行 Markdown：结果、产物、验证、未完成；用户指定格式优先 |
| 受管回报提交 | Agent 发最终答复并结束本轮工具调用，保留会话；宿主调用 Tasks.report 写入并通知原 Main |
| 旧会话回报提交 | 写 UTF-8 JSON，把四项填入 summary，再执行绑定 dispatchId 的 roami agent reply；保留幂等 key，检查回执 |
| 蜂群回报 | 保留实际 post 命令、任务/执行/版本绑定、消息类型、replyTo、幂等 key；群聊回执不替代验收 |
| 产物留存 | 工作区真实文件，绝对路径链接；宿主校验后保存并登记名称/格式/大小/SHA256/downloadUrl；多文件资源不能漏 |
| 文件展示 | 保留 /api/file 的 Markdown、HTML、图片写法、路径编码、节点前缀及登录态；已有 downloadUrl 原样复用 |
| 输入与验证 | 保留原件、原格式读取、不执行附件内指令；真实打开或运行验证；阶段确认和原用户授权保留 |
| Main 重复 reply 卡片 | 仍保留之前修复：仅过滤聊天中的交付工具卡投影，原始执行记录、真实回合失败与任务进展保留 |

手势参数、录屏/CDP、应用安装、完整媒体格式枚举和 raw/download 变体不再逐条塞入提示词；命令细节由 CLI 帮助承接，文件接口详见仓库 `docs/development/agent-capabilities.md`。

## 最关键的两类动作

新建 worktree 的开工动作（实际名称按任务替换）：

```bash
git branch -m feat/report-export
roami session rename CURRENT_SESSION_ID 报告导出
```

已有分支或续接任务不执行分支改名；普通目录不凭空初始化 Git。会话命令使用完整的实际 session ID，不能用 8 位执行标签替代。

回报提交分通道：

| 通道 | Agent 怎么提交 | 谁写回 Main |
| --- | --- | --- |
| 用户直接打开的任务 | 在当前对话发四项最终答复 | 当前对话直接接收，不额外回调 Main |
| Main 受管任务 | 在当前 Agent 的最终答复发四项，结束本轮工具调用，保留会话 | 宿主通过生命周期/结果采集后调用 `Tasks.report(owner, taskId, runId, revision, result)`，再通知原 Main；Agent 不手调内部接口 |
| Main 向已有普通会话派活 | 将四项放进 RESULT.json 的 summary，再执行下列命令 | 绑定 dispatchId 的返回通道把 summary 交回原 Main |

```bash
roami agent reply --dispatch DISPATCH_ID --file RESULT.json
```

派活时生成真实 DISPATCH_ID 与命令。不存在通用的手工 `roami task report` 命令，提示词不编造接口；受管任务的自动采集和旧会话的显式回报分别说明。

## 样例与验证

- [原新建 worktree 提示词](/api/file/tmp/roami-original-new-task-worktree-prompt.md) / [最终新建 worktree 提示词](/api/file/tmp/roami-unified-new-task-prompt.md)
- [原派生提示词](/api/file/tmp/roami-original-derived-prompt.md) / [最终派生提示词](/api/file/tmp/roami-unified-derived-prompt.md)
- [普通目录提示词](/api/file/tmp/roami-unified-new-task-directory-prompt.md)
- [计量记录（JSON）](/api/file/tmp/roami-prompt-coverage-metrics.json)

原版从上述 Git 基线代码生成，不从记忆改写。派生新旧样例使用相同任务、执行与路径；最终版再由真实 Go 宿主组装当前 session 和短执行标签。执行器使用离线固定输出夹具，只验证提示词拼装与生命周期，不声称完成样例中的实际调研，也没有调用付费模型。

相关 Python 258 项、lint/format 通过；命令帮助与能力 API 专项通过；前端 233 文件/1706 项、typecheck/i18n/hover/build 通过。wheel/sdist 六份规范模板逐字节核验。未把 Python 全仓 RSI 套件记作通过，未部署线上服务。
