# 新任务的会话能力说明

桌面和手机的新建任务弹窗、项目任务输入框，以及文件页的“用 Agent 打开”都会在创建会话前读取 `GET /api/agent/capabilities`，在用户任务和工作区简报之后追加能力说明。新任务保留已有工作区简报；文件入口保留原文件任务。用户任务以独立一级标题 `# 任务：`（英文为 `# Task:`）开始，标题前后留空行，与能力说明分开。未选择 Agent 或未填写任务时不注入。

说明保存在 `~/.roami/agent-capabilities.md`；配置了 `ROAMI_HOME` 时随该目录迁移，兼容 `ROAM_HOME` / `TTMUX_HOME`。首次读取时从 `backend/api/prompts/agent-capabilities.md` 创建，权限为 `0600`。读取时自动升级内容完全匹配的已知历史内置模板，保留用户编辑过的文件。每次创建任务都会重新读取，因此编辑后无需重启。留空文件可关闭能力说明注入；删除文件后下次读取会重新生成默认内容。

专业 Agent 启动命令统一补充自动权限参数：Claude Code 使用 `--dangerously-skip-permissions`，Codex 使用 `--dangerously-bypass-approvals-and-sandbox`，OpenCode 使用 `--auto`，Pi 无需额外权限参数。用户自定义命令中的明确权限参数保持有效。

默认内容按职责分节：每组先一句话概括用途，再给少量基本命令。帮助只在开头统一说明：`roami --help` 看总览，命令组/子命令加 `--help`；不再逐组重复帮助或完整使用教程。

新建任务和受管专业执行器共用 `backend/api/prompts/agent-capabilities.md` 这一能力索引。受管执行器只额外携带本次 CLI 路径、私有能力上下文及必要调用参数。回调、产物保留和文件链接分别由任务回报通道模板说明，不混入能力索引。

具体协作流程按需读本机 `roami-session`、`cc-swarm` 或 `dev-roles` skill；具体浏览器、手机和项目操作查看对应命令的帮助。安装器仍按既有机制分发技能。

`{{FILE_BASE}}` / `{{FILE_RAW_BASE}}` / `{{FILE_SERVE_BASE}}` 在提交时替换成当前节点的 `/api/file` / `/api/file/raw` / `/api/file/serve`（多机时带 `/n/<nodeId>` 前缀）。优先使用直接路径链接，文字注明文件名或格式：

```markdown
[报告（Markdown）]({{FILE_BASE}}/tmp/report.md)
[代码（Python）]({{FILE_BASE}}/tmp/demo.py)
![预览]({{FILE_BASE}}/tmp/demo.png)
[播放视频（MP4）]({{FILE_BASE}}/tmp/demo.mp4)
[播放音频（MP3）]({{FILE_BASE}}/tmp/demo.mp3)
[查看文档（PDF）]({{FILE_BASE}}/tmp/demo.pdf)
[打开页面（HTML）]({{FILE_BASE}}/tmp/demo/index.html)
[下载报告（Markdown）]({{FILE_BASE}}/tmp/report.md?dl=1)
```

直接路径按 URL 路径规则编码（各段分别编码，保留 `/`），例如 `/tmp/demo image.md` 写成 `{{FILE_BASE}}/tmp/demo%20image.md`；`#`、`?`、`%` 分别编码为 `%23`、`%3F`、`%25`。完整编码的绝对路径也兼容。先按文件系统绝对路径查找，路径不存在时按 **Roami 后端进程的工作目录** 解析相对路径（不是当前 Agent 会话的工作目录），因此生成链接应始终使用真实存在的绝对路径。绝对路径存在时优先，不会改为读取同名相对文件。HTML 的相对资源沿用同一个路径入口。

各接口的返回格式与用途：

| 入口 | 返回内容 | 用途 |
|---|---|---|
| `/api/file/tmp/report.md` | 原始文件字节，按文件名判定 Content-Type | 默认文件链接，`?dl=1` 下载 |
| `/api/file/raw?path=%2Ftmp%2Freport.md` | 原始文件字节 | 明确需要 raw 时使用，绝对路径完整 URL 编码；`&dl=1` 下载 |
| `/api/file/serve/tmp/demo/index.html` | 原始文件字节 | HTML 与相对资源，兼容既有链接 |
| `/api/file?path=%2Ftmp%2Freport.md` | 含正文和元信息的 JSON，正文有大小限制 | 文件阅读器内部读取，不能当作排版预览链接 |

直接路径和 raw 都不在后端把 Markdown 转成 HTML。手机会话使用下面的文件阅读器渲染；桌面仍由新标签页的浏览器处理，Markdown 不保证排版显示，需要排版交付可另附 HTML。`/api/file/raw/tmp/demo.png` 路径别名也继续兼容。

手机端点击 Markdown 中的同源文件链接，会在会话之上打开独立预览页；页面返回按钮与系统返回键都关闭预览并回到原会话，保留滚动位置。直接路径链接通过 HEAD 响应的 `X-Roami-File-Path`（URL 编码）取得服务端解析后的绝对路径，再复用文件阅读器展示 Markdown、HTML 或媒体。显式 `dl=1` 下载链接沿用下载行为，桌面链接仍在新标签打开。

文件接口和说明接口均要求 Roami 登录态。模板读取失败会阻止创建任务，并提示检查文件，避免留下没有收到任务的空会话。已有会话和恢复对话不会自动补发说明。

模板是提供给 Agent 的可编辑文件内容，按 i18n 规范的文件内容例外保留中文；产品错误提示同时提供中文和英文。

自动迁移仅覆盖已登记指纹的历史默认模板。自定义模板需手动同步新增内容，或在备份后删除该文件，使下次读取生成新默认模板。

## 受管派生任务

Main 派生的专业 Agent 任务使用 Markdown 简报，依次包含 `# 任务：`、开工准备、交付要求、执行资料与 Roami 本机能力。续接只带入本次新增要求及续接交付说明。能力查询命令和带引号的路径变量放在 Bash 代码块中，长路径仅声明一次；签名上下文仍绑定当前任务、执行与版本，不得复制其内容到交付物。

新启动 spec 显式声明 `promptFormat=markdown-session`，末尾执行上下文注明真实当前会话的稳定 ID；新启动同时设置 `shortExecutionLabel=true`，执行标识显示为摘要前 8 位，仅供识别，不作为命令参数或绑定键。内部继续使用完整执行键和摘要。ID 从本次启动回执读取；恢复到新会话时不沿用旧目标 ID。未声明格式、此前 `markdown` 格式及未开启短标识的历史 spec 保留原提示词，确保已有执行的提示词哈希、续接、恢复和取消校验保持有效。提示词正文属于 Agent 对话内容，按国际化规范例外保留中文。

普通新建任务在开工准备中注明当前会话稳定 ID；生命周期创建在分配会话后替换 `{{SESSION}}`，文件入口使用创建接口返回的 ID，旧会话派活使用已解析的目标 ID。改展示名不会改变这些 ID。命令索引同时列出分组帮助与子命令帮助，例如 `roami session --help`、`roami session fork --help`；这些帮助入口无需启动浏览器、连接服务或创建会话。

## 共用的执行与交付约定

`backend/api/prompts/task-execution.md` 是新建任务、派生专业任务及原生子智能体共用的开工、过程回报、产物与完成回报约定。`GET /api/agent/capabilities` 在原 `content` 之外返回 `executionGuide`，前端在准备事项之后合并；可编辑能力文件留空只关闭能力说明，不关闭执行和交付要求。

受管、普通会话、旧会话返回通道与蜂群消息分别由 `task-report-*.md` 补充。受管任务的最终答复由宿主采集、保留产物并形成原 Main 的完成回调，执行器不自行调用内部 report 接口。旧会话返回通道仍需明确的 `roami agent reply`，不冒充自动归档。详细架构、产物数据流和验收见 [统一开工、回报与产物约定](../design/20261111-derived-task-prompts/unification.md)。

普通受管任务只显示版本和提交方式，完整 task/run/Main 绑定由宿主及私有上下文持有；蜂群消息保留 Agent 真正需要提交的完整协议字段。完成回报默认采用“结果、产物、验证、未完成”四行。受管任务由 Agent 提交最终答复、宿主自动调用 `Tasks.report(...)`；旧会话通道写 JSON 后执行实际 `roami agent reply`。开工与精简的逐项对照见 [覆盖核对](../design/20261111-derived-task-prompts/coverage-audit.md)。
