# 新任务的会话能力说明

桌面和手机的新建任务弹窗、项目任务输入框，以及文件页的“用 Agent 打开”都会在创建会话前读取 `GET /api/agent/capabilities`，把能力说明放在用户任务之前。新任务保留已有工作区简报；文件入口保留原文件任务。用户任务以独立一级标题 `# 任务：`（英文为 `# Task:`）开始，标题前后留空行，与能力说明分开。未选择 Agent 或未填写任务时不注入。

说明保存在 `~/.roami/agent-capabilities.md`；配置了 `ROAMI_HOME` 时随该目录迁移，兼容 `ROAM_HOME` / `TTMUX_HOME`。首次读取时从 `backend/api/prompts/agent-capabilities.md` 创建，权限为 `0600`。已有文件不会被覆盖，每次创建任务都会重新读取，因此编辑后无需重启。留空文件可关闭能力说明注入；删除文件后下次读取会重新生成默认内容。

默认内容作为 Roami 能力索引：先引导读取本机 `roami-session` skill，覆盖会话查询、派生、派活、续派、swarm 建群、成员、看板、消息、巡检与验收；复杂协作再按需读 `cc-swarm`、`dev-roles`。安装器通过 `skills/sync-skills.sh` 同步到 `~/.claude/skills` 和已存在的 `~/.codex/skills`；自定义目录以实际安装为准。Skill 不可读时回退到 `roami session help` 和索引中的命令，不自动安装。当前 CLI 没有 `swarm help`，子命令也不统一支持 `--help`。

派生会话不等于复制 Agent 对话或创建 worktree。向 shell 发的是启动命令，向已运行 Agent 发的是任务；发送成功不能替代验收。当前会话指挥的群使用 `--no-master`，成员显式指定 `--role member`，避免额外启动或误认指挥。提示词同时介绍 `roami chrome` 浏览器操作、截图录屏和文件链接。

Android 能力通过 `roami adb <参数...>` 调用本机系统 ADB，保留原生参数、标准输入输出与退出码；无参数、`roami adb help` 或 `roami help adb` 查看 ADB 帮助。该入口不依赖 Roami 服务、登录或插件，也不自动安装 platform-tools。它遵循 ADB 的 `-s` / `ANDROID_SERIAL` 选择方式，不读取 Roami 手机镜像配置；提示词要求先列出设备，再显式指定序列号。

手机指引覆盖设备状态、PNG 截图、原生 UI 树、设备像素坐标、真实点按与滑动、按键和简单文本输入、App 启动、APK 安装、文件传输、日志与 Chrome CDP 转发；说明中文输入和可调试 WebView 的限制。截图等产物先保存或拉取到本机，再使用文件链接交付。参数按 argv 传递，Roami 不额外拼 shell；`adb shell` 内部仍遵循原生 Android shell 语义。

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

更新仓库默认模板不会自动迁移已保存的 `agent-capabilities.md`。已有安装需手动同步文件链接段，或在备份自定义内容后删除该文件，使下次读取生成新默认模板。
