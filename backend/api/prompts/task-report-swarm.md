## 蜂群过程回报

群 `{{SWARM}}`，成员 `{{MEMBER}}`。在工作区写 MESSAGE.json：

```json
{{MESSAGE}}
```

替换实际消息文件路径后执行：

```bash
{{POST_COMMAND}}
```

- 讨论用 `progress`；需 Main 处理用 `question`、`blocker` 或 `handoff`。回复用 `reply`，`replyTo` 填原消息 ID。
- 沿用本次任务、执行、版本；新消息换 key，同次重试保留 commandKey、messageKey 与内容。
- 回执不代表 Main 已回复或验收；不能用发一条群聊消息替代交付，最终仍走受管任务回报。

查看状态与回复：

```bash
{{STATUS_COMMAND}}
```
