# 旧会话的有界原文读取（#898）

## 产品设计

Main 查看过去的决定或回执，应取得一页可追溯原文，而不是把全部旧工具协议重新注入当前模型请求。原会话、压缩摘要、用户约束与历史均保留，不改变模型路由、容量或预算。页面不增加配置入口。

真实群聊 turn7a67c48af0f947b0ae96facedd3e6535 调用无参数 conversation_history 后，PromptBuilder 关闭 main_briefing，真实输入膨胀至983010 tokens（估算1090911）；此前另一轮约76万tokens发生上游400。提醒模型别读全量不能替代底层有界读取。

## 用户故事

- 引用旧决定时，Main 先读最近一页，再沿游标查更早记录；可按原消息ID分段读取长原文。
- 原工具回执能作为历史证据查看，不能重新成为当前工具调用或新的用户授权。
- 删除/忘记的内容、其他项目、旁支和当前/未来轮次不能因历史读取重新出现。

## 技术设计

`conversation/history_read.py`：按真实 tool binding 的 owner/conversation/turn branch 构建 lineage，并以当前轮第一条消息划定上界。只读旧 user/assistant/tool 记录，复用 omission 与 task_user_request 规则；不使用当前 active branch 替换原 turn branch。

`conversation_history` 默认读取10条，最多20条，每条返回2000字符的规范化JSON片段，整个响应最多64000 UTF-8字节。返回 source messageId、role、status、offset/nextOffset 和 olderCursor/hasMore。单条长记录以 messageId/offset 继续，不能悄悄当作完整原文。分页游标可以跨过后来忘记的记录，但其内容永不返回；旁支和当前/未来位置拒绝。

历史内容只放在本次工具结果中，并标为历史数据；不作为外层 assistant/tool 消息重新拼接。剥离 replyPreview 与无关内部上下文，保留原文与工具字段。PromptBuilder 始终维持 Main briefing，去掉“成功调用一次就恢复整段历史”的开关。无需新表、后台任务、模型调用或权限扩大。

## 验收

覆盖 UTF-8 响应上限、巨大工具记录与分段原文、顺序/游标/空页前进、父分支切点、原turn绑定、owner/项目/旁支隔离、删除/忘记与任务指令来源、当前/未来轮次、replyPreview 不入模型、原始回执语义及一轮多次读取。原显式历史测试改为验证证据页，不再断言将旧工具协议重接到当前链。真实私有长历史副本/只读生产读取和 prompt manifests 证明有界，不修改线上记录或模型参数。

专项47项通过。真实原Main数据库以 mode=ro/query_only 直接调用新读取函数：10条旧记录、22058字节、4.78ms，保留更早游标；新函数尚未部署。这是读取响应测量，不是整个模型请求或端到端延迟测量。原全量恢复的983010 input tokens来自旧生产请求的真实trace。证据在 `/tmp/okr-member-migration-20261111/bounded-history-real-readonly-result.json`，未写生产数据库或调整模型参数。
