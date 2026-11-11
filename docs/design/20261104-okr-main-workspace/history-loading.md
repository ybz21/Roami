# 长期 Main 的聊天历史读取

## 产品设计与用户故事

用户打开长期运行的OKR Main，应立即看到近期对话及同轮工具活动。读历史失败不能被解释为
发送失败；已投递消息沿用原键对账，不能因为页面空白重复派工、重建Main或重发外部动作。

真实生产页出现“请求未完成，请重试”。独立只读调用同一个分页函数，50条请求返回48条消息、
98项活动和约70KB，耗时7.04秒；cProfile中7.005秒花在activity_summaries的SQLite查询。
该会话三万余事件，查询为找到近期消息的活动而遍历全部历史JSON。单writer排队进一步放大
耗时。证据在`/tmp/okr-member-migration-20261111/page-readonly-profile.txt`，跟踪#892。

这是历史读取性能问题。另一次Main通过conversation_history恢复全量历史，估算约76万token
后上游返回400，是独立的模型请求失败；本修复不更改模型容量、路由、参数、账目或历史内容。

## 技术设计

正式schema28迁移新增partial expression index：仅索引activity为object的事件，键依次为
conversation_id、activity.anchorMessageId、activity.id和event id。分页使用同样的object谓词，
按已选消息锚点读取最新活动，再沿用现有预览剥离、删除过滤、400项上限和响应大小预算。
不按event kind硬编码，未来新增kind携带合法activity仍可读。消息游标、分支谱系及顺序不变。

迁移只加索引，不改业务行或执行状态；失败在原事务回滚，重试走既有upgrade_schema。
Go备份允许版本同步到28，部署必须是包含新迁移和读取逻辑的完整运行包，不手改线上数据库。

## 验收

专项覆盖更新后的最新活动、不同锚点、未来kind、预览剥离与实际索引执行计划；真实旧库升级
失败回滚后事实不变，重试通过，旧出版历史升级和分页/活动专项共29项通过。隔离副本做新旧
结果逐字段对比和耗时记录，不在生产上试建索引。合入前跑quick/full，部署后重新验证真实
页面读取、Main回复和原成员继续；后续结果补在本目录，不把模型上游400算作本索引已经修复。

真实数据库固定只读快照的独立对比：同一组48条消息、95项活动，旧查询2143.33ms，新查询
49.83ms；迁移487.42ms。结果逐字段相等，规范化输出SHA为
`4145001c84e9295d4acca3dcdc44f22747ae4ad2cafee1ae77943f6a96e2b4d0`。
记录在`/tmp/okr-member-migration-20261111/history-read-performance/result.json`。
原生产库未写入；这是固定副本上的查询耗时，不是生产整体CPU、内存或端到端延时的结论。
