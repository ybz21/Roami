# 新任务的会话能力说明

新建任务弹窗和项目任务输入框会在创建会话前读取 `GET /api/agent/capabilities`，把能力说明放在工作区简报之后、用户任务之前。未选择 Agent 或未填写任务时不注入。

说明保存在 `~/.roami/agent-capabilities.md`；配置了 `ROAMI_HOME` 时随该目录迁移，兼容 `ROAM_HOME` / `TTMUX_HOME`。首次读取时从 `backend/api/prompts/agent-capabilities.md` 创建，权限为 `0600`。已有文件不会被覆盖，每次创建任务都会重新读取，因此编辑后无需重启。留空文件可关闭能力说明注入；删除文件后下次读取会重新生成默认内容。

默认内容介绍 `ttmux` 会话命令、`chrome` 浏览器命令和文件链接。`{{FILE_RAW_BASE}}` 在提交时替换成当前节点的 `/api/file/raw`（多机时带 `/n/<nodeId>` 前缀）。文件绝对路径必须完整 URL 编码：

```markdown
![图片]({{FILE_RAW_BASE}}?path=%2Ftmp%2Fdemo.png)
[播放视频]({{FILE_RAW_BASE}}?path=%2Ftmp%2Fdemo.mp4)
[下载文件]({{FILE_RAW_BASE}}?path=%2Ftmp%2Fdemo.pdf&dl=1)
```

文件接口和说明接口均要求 Roami 登录态。模板读取失败会阻止创建任务，并提示检查文件，避免留下没有收到任务的空会话。已有会话和恢复对话不会自动补发说明。

模板是提供给 Agent 的可编辑文件内容，按 i18n 规范的文件内容例外保留中文；产品错误提示同时提供中文和英文。
