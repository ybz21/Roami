# Main 建团队来源准入验收（2026-11-07）

关联 #744，仅本批来源校验与原子提交。尚未部署，不表示成员收件箱、自主协调或原宣传团队交接完成，issue 保持开放。

- 修复前同一测试真实失败：返回 TASK_REQUIRES_ORIGIN_MESSAGE 后，swarm_groups/commands 已从0变1，events从1变2，保留 baseline.log。
- 修复后106项来源/Swarm命令/项目Main/长期成员/CLI身份相关回归通过；14项新增用例覆盖缺失来源（含省略Main）、空binding、错误对话、非user/已结束turn、遗忘、查询与提交间删除，拒绝后不新增团队、回执、事件、对话或job。
- 真实mailbox.claim + chat.interrupt复现停止记录已持久化但轮次仍running时的迟到建团队。复用context admission后，在初查和写事务都拒绝已停止/撤回的上下文，拒绝不新增事实；stop-baseline.log保留实际失败。
- 合法绑定始终继续实际来源Main，不创建首页替身；模拟数据库提交后丢失回执，原来源已与团队一起提交，重试仍返回同一团队。原origin只补缺失，不替换已保存来源。
- 仓库full通过：3838 passed, 48 skipped, 6 subtests passed in 1251.19s (0:20:51)。Go全量、运行时lint/format、前端typecheck/i18n/hover/build通过。没有前端产品代码改动，未额外运行Vitest；无手机操作或生产写入。
- roami chrome --fresh将真实失败/通过日志渲染为离线截图，不冒充产品UI或生产模型验证；临时浏览器自行关闭，仅经isolated-roami --stop回收记录的私有测试实例。报告、截图与原日志保留。
- 保留完成回报和普通completion不可续派的原保护；后续受限协调必须实现独立的原目标委托、收件箱与故障矩阵，不能把本修复当成该机制已交付。

证据目录：/tmp/okr-origin-admission-20261107/，含baseline.log、stop-baseline.log、stop-target.log、full.log、test-evidence.html/png、screenshot-cleanup.json；正常提交钩子quick的结果另见commit.log。
