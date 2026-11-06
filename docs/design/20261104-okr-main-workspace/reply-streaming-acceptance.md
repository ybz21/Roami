# Main 正文流式验收（2026-11-07）

关联 #748。实现候选尚未部署，生产 Main 与真机验收未计完成，issue 保持开放。

- 最终仓库 full 通过，Go、运行时 lint/format/pytest、前端 typecheck/i18n/hover/build 及前端全量均通过。
- Python：3811 passed, 48 skipped, 6 subtests passed in 934.39s (0:15:34)。
- 前端：Tests  1546 passed (1546)。
- 70项相关后端专项、8项相关前端专项、4项独立安装生命周期回归通过。覆盖真实参数增量、Unicode/跨片转义、其他字段隔离、双工具、重试撤回、核验拒绝立即撤回、旧lease迟到失败、取消/延期/遗忘/恢复与终止重放。
- 自有 roami chrome 页接入隔离 Python Runtime，经真实 HTTP SSE 验证两次生成增量、重开恢复、核验后单次替换、停止后不复活、首页/项目独立会话。四档桌面及390紧凑模拟无文档溢出。使用受控模型，不冒充生产模型或真机验收。
- 候选渲染共用 ChatMessage/Markdown，核验前不自动加载图片；正式消息保留既有能力。预览字段不成为正式正文、记忆来源、通知或任务验收结果。

证据：/tmp/okr-reply-preview-20261107/ 的 qa-final.log、browser-proof.json、runtime-final-target.log、ui-target.log、installation-check.log 和截图；最终全套日志为 /tmp/okr-shared-conversation-20261107/preview-full5.log，退出回执0。

前几轮未完成的检查日志保留。架构边界与工具事件契约专项已修正；重复测试根目录的遗留socket被隔离保护拒绝，未接管或清理未确认资源。最终运行采用新建的独立测试目录。
