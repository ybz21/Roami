# Main 正文生成的流式通道

关联 #748；前置 #749 共用对话组件。本节为实现候选，尚未部署；原 Main 的线上验收仍待完成。

## 用户体验

首页和项目 Main 使用同一组件。生成时逐步显示真实的候选正文，并标记“生成中”；模型提交后进入“核对中”，通过来源核验后才成为正式回答。候选被拒绝、取消或改写时撤回，由同一轮的新候选或错误状态接续；不保留两份重复回答，不为候选提供记忆保存或完成凭据。

普通助手正文沿用已有 message.delta 通道。`reply(text)` 的函数参数流提供专用候选预览，正式 message.delta / message.completed 的契约不变。JSON 值、其他工具参数、思考内容与工具原始 JSON 不展示为正文。没有真实增量的上游保持正常等待，不做客户端打字机。

## 底层边界

1. Chat Completions 适配层保留原有完整 tool 事件，另外输出内部工具增量，含索引和已拼接的工具名/参数。内部增量不直接下发浏览器。
2. Main 循环只在强制最终 reply 的场景识别唯一 `reply` 调用的顶层 text 字符串。流解析须处理跨片 JSON 转义与 Unicode；不推断 json 值为 text，不输出其余字段。多工具批次、非法字段和解析失效会撤回候选。
3. TurnJournal 将候选作为独立 replyPreview 元数据保存于当前模型消息；标准 content.text 保持为空。专用预览事件携带候选身份和 offset，与元数据在同一事务更新。保留原有上下文 admission / lease 检查，节流和限制候选体积。
4. 预览元数据不作为模型消息、来源核验的正式回答、通知、团队回报、记忆来源或任务验收。正式提交的工具参数仍按现有执行记录处理。工具核验仍走原 SourceReplyReview，不改模型路由、参数、费用和配额。
5. 开始下一模型消息、生成正式回答、失败、中断、延期、遗忘均撤回旧候选。工具提交后的候选仅以“核对中”呈现；原消息转为完成状态不代表回答已通过。
6. 快照和 SSE 使用同一个候选结构；读取仅保留当前运行轮次、仍可见消息的候选。终止轮次的残留元数据不展示，进程恢复也不能复活旧候选。节点、conversation、branch、turn、model-message 共同隔离；不按展示名路由。
7. 共用 AgentMessageView 渲染候选状态；最终回答只走正常正式消息。候选 offset/身份不符时按已有机制刷新快照，晚到事件不能改写新轮。

已对照 context projection、分页裁剪、兼容快照、记忆来源与进程恢复：在原有消息元数据保存候选，无数据库迁移。正式 content.text 仍为空。来源核验期间候选保留，回到模型上下文时移除预览字段；遗忘/终止/过期执行的快照与重放不再提供候选内容。

## 代码与协议

- `protocol/reply_text_stream.py` 解析顶层 text；`protocol/reply_stream_preview.py` 负责单工具判定、约 100ms/1024字符节流和核验阶段转换。均只依赖 protocol/标准库，core 不引入存储实现。
- `providers/chat_completions.py` 发出内部 tool_delta，参数采用独立字符串快照，完整 tool 事件的执行时机不变。内部工具增量不改变原有网络重试条件；如上游安全重试，先撤回候选并清空工具索引/片段状态，不能拼接两次请求。完整工具仍只在响应结束后执行。
- `storage/turn_journal.py` 在事务内更新 replyPreview 并发出 reply.preview；`storage/reply_previews.py` 检查原会话、活动分支、轮次、lease 和上下文准入。旧 lease 的 fail 不清除新 lease 的候选或状态。
- reply.preview 包含 messageId、turnId、Unicode offset、增量 text、state、clipped 和可选 reset/clear。候选限制为8000个字符，只限制界面预览，不修改模型生成、正式答案或网关额度；超出时提示完成后查看全文。快照为正在生成的候选保留相应字节空间。
- `conversation/pages.py` 和兼容 messages 接口使用同一可见性判断；终止或被遗忘内容的候选事件在对外重放时清除正文。正式 contentOffset 不与候选 offset 混用。
- `context/projection.py` 排除预览字段；`memory/writer.py` 不接受 reply.preview 事件作为记忆来源，也不将候选元数据计入消息来源快照。
- 前端 `agent-protocol.ts` 校验轮次、分支、模型消息和 offset；`AgentReplyPreview` 由共用 AgentMessageView 使用。候选共用 ChatMessage/Markdown，但核验前不自动加载图片；最终回答恢复原有正常渲染。

## 验收门槛

- 延迟工具参数流在模型结束前呈现两次以上候选增量；正式正文和 completed 在核验前均不存在。
- 保留最终回复协议、来源审核拒绝、JSON 类型/字面值、受管任务与已验证结果的所有既有保护。
- Unicode/跨片转义、text 非首字段、其他工具、双工具批次、字段冲突、断线重连、快照裁剪、取消、失败、延期、遗忘、过期 lease、切节点和切分支均有证据。
- 真实页面通过 roami chrome 验证共享组件的候选/正式替换和错误恢复。模拟不代替原 Main 的线上验收；未完成部署与真实回归前 #748 不关闭。

隔离 Runtime/浏览器证据位于 `/tmp/okr-reply-preview-20261107/`；使用受控模型参数流，不代表生产模型或真机验收。

[实现候选验收记录](reply-streaming-acceptance.md)。
