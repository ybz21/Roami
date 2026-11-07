# 对话正文与工具过程

## 产品设计与用户故事

用户发出的消息直接完整显示，不使用任务描述的三行摘要与“展开／收起”。首页、项目 Main 与原生成员沿用 `ChatMessage` 的 Markdown、图片引用、时间和复制功能。任务详情的摘要规则继续由 `TaskDescription` 负责。

Main 对话复用首页的完整过程：先看到生成中的正文、正在执行的工具与状态，工具完成后能查看输入输出，最后显示回答。展开执行记录属于工具详情，不是用户消息折叠。

## 技术设计

`AgentChat` 与 `OkrMainChat` 已在 #749 共用 `AgentConversation`，`useAgentThread` 接收真实 SSE，`agentTimeline` 排列正文与工具事件，`AgentActivity` 展示运行、结果及详情。#750 增加后端真实回答增量预览。项目适配器只恢复独立 Main 身份与上下文，不能选用首页 Main，也不应另写只显示最终回复的消息列表。

本轮移除 `NativeConversation` 对 `TaskDescription` 的正文替换，删除 `ChatMessage.renderUserText` 旁路和两条专用折叠样式。原生成员与共用 Main 消息现在使用同一正文实现，不通过样式强行展开摘要。工具调用、系统提醒和推理的详情结构保留。

## 验收记录（2026-11-07）

- 首页与项目 Main 的集成用例走真实 hook/ReadableStream/SSE：最终回答前显示工具 running、已读输入与 succeeded 输出，随后显示两段回答增量并保留工具记录。
- 自有隔离页通过 `roami chrome` 操作真实组件。复现旧原生成员三行截断，修改后 Markdown 全文无需点击可见。首页和项目 Main 分别验证中间正文、工具状态、输出和最终回复；共 22 项断言。
- 项目 Main 与原生成员各检查 1280、1920、2560、3440、390 CSS px，共十组布局，无 document 溢出。390 为紧凑模拟；遵守不触手机的边界，未记真机通过。
- 本机证据：`/tmp/okr-full-messages-20261107/`，含 before/after、工具过程截图和 `browser-proof.json`。事件来源为受控隔离服务，没有调用真实模型或改动生产数据。
- 前端全量 211 文件、1547 测试通过；typecheck、i18n、hover、生产 build 和仓库 full 门禁通过。没有 Python/Go 变化，按仓库作用域规则跳过对应全套。

当前生产仍是旧版本，不能把隔离验收或代码合入当成线上已生效。真实流式线上验收继续跟踪 #748；升级准入拒绝时不强制重启已有任务。
