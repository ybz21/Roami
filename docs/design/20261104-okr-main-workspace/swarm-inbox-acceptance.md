# 群聊持久收件箱验收（2026-11-07）

关联 #744，依赖 #752 的来源准入与停止修复。本批仅可靠消息、收件箱及实际读/答复回执；自动协调批次、原目标委托、handoff/completion合并与原宣传团队真实交接仍未完成。尚未部署，不关闭issue。

- 前一候选c39e939b的full通过：3864 passed, 48 skipped, 6 subtests passed in 1273.01s (0:21:13)，正常quick3864项通过。该候选随后因新发现的Main停止竞态暂缓，不作为新修复后的最终门禁证据。Go全量、运行时lint/format、前端typecheck/i18n/hover/build通过；没有前端产品源码改动，未额外重跑Vitest。
- 最终122项合并专项通过；另Go CLI/存储/服务三个包全量通过。覆盖稳定业务键跨调用重试、改内容/路由冲突、作者/任务轮次分域、跨项目拒绝、SQL故障完整回滚、已读未答复仍待处理、成员回复不代替Main核验、旧run与关闭会话拒绝、原命令未知回执恢复、Main不通知自己、无关post不能充当答复凭据。
- 私有schema22备份副本升级24，60张原表的所有原字段/行哈希一致、原Main仍在、foreign_key_check零错误。新增routes/inbox两表均为空，不替历史消息猜作者、路由或已送达。生产库只读，未迁移线上。
- 自有roami chrome接入真实Python Runtime/Core ToolGateway与HTTP/SSE。真实新Go CLI通过私有Unix socket提出成员问题；人工在原Main输入处理请求，实际注册inbox/post工具读取后答复；原成员CLI取得同一replyTo回复。两项目同本地业务键均隔离，群聊与私聊保持各自范围。16项断言通过，四档桌面与390紧凑模拟无文档溢出。
- 使用受控模型和Go项目HTTP/鉴权夹具，未启动真实执行器，不冒充真实Go项目API、生产模型、自动Main唤醒或真机验收。回复只证明通信，不把任务改成已验收。
- 自有页、API/Vite与浏览器均已关闭，三个端口与进程清空，profile移除，仅用同一isolated入口回收记录的测试实例。浏览器启动器因最后context关闭后未决顶层await退出13，已如实记录；实际浏览器已结束，未重新跑QA来掩盖日志。证据保留。
- 第一轮full因后续真实停止竞态被中断，不作为最终通过证据；最终full2包含#752最新停止保护。正常提交钩子quick随本批提交执行；结果记录于commit.log，未通过不会提交或发布PR。

独立复核又通过真实Runtime的accept/claim/interrupt复现：持久stop已记录时，迟到的Main post仍新增一条群聊消息。修复在读写事务核验当前Main turn/context，新增停止后post无残留、旧回执可恢复、停止后不标已读及缺失/结束/旧lease回合拒绝五项。收件箱30项专项通过，最终full与正常提交钩子在此修复后重新执行；旧安装包保持未激活。

证据目录：/tmp/okr-swarm-inbox-20261107/，含stop-combined-target.log、go-target3.log、full.log、live-copy-migration-proof.json、browser-proof.json、member-reply-a/b.json、qa.log和cleanup.json。当前未修改原项目/模型路由/费用账目/busy或手机。

full3未通过：3102项先通过后，旧CLI身份测试的虚构progress-turn被新守卫拒绝；另一个post-turn夹具也已定位。两项均改为真实accept/claim的运行回合，原身份、命令回执与不新增turn的断言保留，不放松守卫。最终full4在夹具修正后执行；产品代码与已通过16项浏览器复验的版本一致。

最终Main停止修复的full4：3869 passed, 48 skipped, 6 subtests passed in 1053.51s (0:17:33)。Go全量与运行时lint/format、前端typecheck/i18n/hover/build通过；此后正常commit quick记录见commit-main-stop.log。新守卫下的roami chrome真实Core/CLI链路16项再次通过，五档布局无溢出；自有三个服务均退出0、端口/profile清空，两个私有fixture经同一隔离入口停止。首次QA启动因夹具未初始化layout失败的日志保留，修正夹具初始化后重验，不计前次通过。
