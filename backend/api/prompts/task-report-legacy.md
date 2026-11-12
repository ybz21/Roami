# 回报通道

本次向已有普通会话派活，聊天回复不会通知 Main。结束前写 UTF-8 RESULT.json，填入实际结果、产物链接、验证和限制：

```json
{"key":"final","status":"completed","summary":"结果：<具体结果>\n产物：[报告（Markdown）](/api/file/实际绝对路径/report.md)\n验证：<实际检查及结果>\n未完成：<剩余工作；无则写无>"}
```

将 RESULT.json 换成实际路径后执行：

```bash
{{REPLY_COMMAND}}
```

`summary` 返回原 Main。进展用 `progress`，阻塞用 `blocked`（可附 `question={prompt,options:[{label,description}]}`，2–4 个选项）；最终用 `completed` 或 `failed`。

新回报换 key，同次重试保持 key 与 JSON 不变；检查成功回执，失败保留 JSON 和产物，不重做已完成的工作。回执不代表验收。

此旧会话通道不会自动归档文件；保留原件，返回 Roami 文件链接或已有 downloadUrl。
