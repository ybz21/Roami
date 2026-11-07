# 原结果回传到原 Main（实现设计）

## 产品设计与用户故事

原 X、B站、数据成员完成一轮后，由原 Main 消费实际结果，审核、回复或续派。已有历史群聊和 Main 不重建。交接消息、执行结果、实际模型读取、验收与发布仍是不同事实。这里只接入真实完成回传，不开放日槽、任意群消息或发布权限。

- 重复回调只恢复已有回执，不重复唤醒 Main。
- Main 忙、等用户或团队暂停时保留待处理，随后复用同一通知。
- 同 run 的结果从 unknown 变为 known，即使状态文字相同，也按真实 result receipt 区分。
- 已冻结/运行的批次和传统 completion 输入不改写；晚到结果只有实际 manifest/task_status 覆盖其 receipt 才能消除通知。

## 技术设计

复用 jobs、task.execution_result_recorded、swarm_coordination_results 与 swarm_result_observations，不另建结果正文库或新 schema。Runner 现有 complete 在原 writer 事务里取得 actual executionReceipt，并尝试项目协调路由。

路由资格来自真实当前任务所属的稳定成员、原群、原 Main、当前有效委托选中的成员和真实来源；没有委托或旧无 receipt 的任务保留传统 completion 路径。暂停时只允许保留待处理通知，不授权模型或派工。任何结果正文或 model trigger 名都不能创建委托。

首个协调通知沿用 task.completion:<run>:<state> 的幂等身份，但 job kind 为受管结果桥接；同状态出现新的实际 receipt 时才追加 receipt 后缀。已经存在的传统 turn.run completion 不修改输入，也不以同 run 就认定新结果已观察。带 coordinationAuthorization 的自动续派结果保留原委托身份；撤销或重新委托后不能回落到普通 completion 绕过范围限制。历史无授权回调不追认长期权限。

新增 storage/swarm_completion_bridge.py 负责资格、原通知身份、冻结 receipt 指针、重放与消费。新增 kind=swarm.coordinate 由既有 Scheduler 处理，无独立常驻线程或每团队轮询。使用原活动事件以保持 UI 状态同步；排队优先级与 Main 并列，真实用户请求优先，避免被大量记忆任务挡住。无资格/撤销保留明确结果，不转投其他项目；Main 忙或暂停则给同 job 增加 available_ms。失败与等待区分，不能因异常换业务键。

消费先核验真实 receipt、当前原成员 task/revision/run、原有效委托以及源内容未遗忘；已由实际 manifest 观察或已冻结到另一个真实批次的同 receipt，仅恢复对应事实。task_status 必须实际 includeResult 且正文 executorResult 的规范摘要匹配同一 receipt，元数据/状态查询不消除结果通知。否则调用现有 enqueue，冻结当时可消费结果和 inbox 输入，原子产生同一个 continuation/Main job，并把桥接 job 标记完成，保留 batch/turn/receipt 回执。正在处理的旧批次不会吞掉晚到事实。

为了保存暂停团队的待处理结果，将委托的“读取仍有效来源”与“允许开始协调执行”区分；默认 current_delegation 继续要求活跃，只有保存通知的内部读取允许暂停，不绕过撤销、项目、原来源摘要/分支或成员校验。恢复后执行仍走默认活跃校验。公开工具与用户输入不能传入这个内部选项。

## 边界与验收

按实际代码进一步验证旧 completion 冲突、相同状态新 receipt、冻结前后晚到、观察前后、暂停/撤销/遗忘、错误项目/成员/轮次、事务失败回滚与重启重放。普通 Main/无委托 completion 必须保持回归。调度接线只有在这些验证和同批次恢复/写入幂等依赖完成后才进入发布候选；本设计、私有 fixture 或投递成功不算真实自动循环。

## 私有候选验证

75项结果桥接、观察、验收、实际回执和任务续派专项通过（48.05秒）。包含真实 writer 事务回滚、相同状态 unknown→known、旧 completion 字节保留、暂停/撤销/来源遗忘、元数据不计正文读取、120项记忆积压与现有 Scheduler 接线。当前未做完整门禁、未提交、未部署；同批次恢复与写入幂等依赖尚未整合，公开目标与日程生产者仍不开放。
