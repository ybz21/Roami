# 新任务的会话能力说明

桌面和手机的新建任务弹窗、项目任务输入框，以及文件页的“用 Agent 打开”都会在创建会话前读取 `GET /api/agent/capabilities`，把能力说明放在用户任务之前。新任务保留已有工作区简报；文件入口保留原文件任务。未选择 Agent 或未填写任务时不注入。

说明保存在 `~/.roami/agent-capabilities.md`；配置了 `ROAMI_HOME` 时随该目录迁移，兼容 `ROAM_HOME` / `TTMUX_HOME`。首次读取时从 `backend/api/prompts/agent-capabilities.md` 创建，权限为 `0600`。已有文件不会被覆盖，每次创建任务都会重新读取，因此编辑后无需重启。留空文件可关闭能力说明注入；删除文件后下次读取会重新生成默认内容。

默认内容介绍 `ttmux` 会话命令、`chrome` 浏览器命令、截图录屏和文件链接。`{{FILE_RAW_BASE}}` / `{{FILE_SERVE_BASE}}` 在提交时替换成当前节点的 `/api/file/raw` / `/api/file/serve`（多机时带 `/n/<nodeId>` 前缀）。raw 入口的文件绝对路径必须完整 URL 编码：

```markdown
![图片]({{FILE_RAW_BASE}}?path=%2Ftmp%2Fdemo.png)
[播放视频]({{FILE_RAW_BASE}}?path=%2Ftmp%2Fdemo.mp4)
[下载文件]({{FILE_RAW_BASE}}?path=%2Ftmp%2Fdemo.pdf&dl=1)
[打开 HTML 页面]({{FILE_SERVE_BASE}}/tmp/demo/index.html)
```

文件链接也兼容将路径直接接在 `/api/file/` 或 `/api/file/raw/` 后面，例如 `/api/file/tmp/demo.png`、`/api/file/raw/tmp/demo.png`。路径按 URL 路径规则编码（各段分别编码，保留 `/`）；完整编码的绝对路径也可用。先按文件系统绝对路径查找，路径不存在时按 **Roami 后端进程的工作目录** 解析相对路径（不是当前 Agent 会话的工作目录）。绝对路径存在时优先，不会改为读取同名相对文件。`?dl=1` 仍可强制下载；HTML 的相对资源沿用同一个路径入口。原有查询参数接口与 `/api/file/serve/...` 不变，Agent 生成链接仍优先使用上面的标准写法。

手机端点击 Markdown 中的同源文件链接，会在会话之上打开独立预览页；页面返回按钮与系统返回键都关闭预览并回到原会话，保留滚动位置。直接路径链接通过 HEAD 响应的 `X-Roami-File-Path`（URL 编码）取得服务端解析后的绝对路径，再复用文件阅读器展示 Markdown、HTML 或媒体。显式 `dl=1` 下载链接沿用下载行为，桌面链接仍在新标签打开。

文件接口和说明接口均要求 Roami 登录态。模板读取失败会阻止创建任务，并提示检查文件，避免留下没有收到任务的空会话。已有会话和恢复对话不会自动补发说明。

模板是提供给 Agent 的可编辑文件内容，按 i18n 规范的文件内容例外保留中文；产品错误提示同时提供中文和英文。
