# 多 OKR 范围绑定：第一批实现

关联 #746，前置[通信机制设计](communication-engine-design.md)及[协调回合契约](swarm-delivery-contract.md)。本批不实现自动唤醒或发布，不改变原 Main/成员/历史，不关闭 #744/#746。

## 产品与故事

两个注册项目可以各有名为“运营团队”的 Swarm，继续各自原 Main、成员与记忆。两边使用相同本地命令键也各自只执行一次；同一目标内同键改内容仍冲突。已有请求在升级后仍返回原回执，不能重新创建团队或给另一 Main 发消息。命令、收件人和项目在提交时固定，页面名称或 cwd 不授予身份。

## 实现边界

首版继续一项目一 OKR，复用 `project_okr_mains(owner_id,project_id)` 作为默认 scope 的权威 Main 绑定，不另建一份会漂移的 Main 注册表。node 由本地运行时数据库限定；不声称多租户或跨节点联邦。定义目录继续使用注册项目根内的 `.roami/okr`。

- `swarm_groups.scope_project_id` 只绑定与现有 canonical Main、owner 及 target 一致的项目。显式给另一个项目或首页 Main 建团队时拒绝。老的不明确绑定保留历史，不按显示名、最新时间或当前目录猜测。
- 名称唯一性改为 owner/project/name；普通无项目团队维持原 owner/name 唯一规则。scope 绑定后不得通过改 target/Main 将原团队搬到其他项目。
- `swarm_commands` 以 owner/project/commandKey 去重。迁移根据原回执引用的实际 Swarm 分域，保留原键、digest、回执字节。无法证明归属的旧记录保留原域，重试不能借新域重做旧请求。
- 人的群聊投递键也必须固定到 Swarm。新 post 在同一事务保存稳定 delivery_key；旧 post 仍沿用旧键，覆盖“消息已落库/实际发送已接受，但 delivery_json 未保存”后的恢复。不因命令分域而把消息再次发送。
- CLI 现有入口已经只接受稳定 `sw-...` ID，不增加全局按名字猜测或新的页面选择器。读写仍检查真实 owner、Main/member、task/revision/run。

## 迁移与模块

schema23 重建 groups/commands 以移除旧唯一约束，并保留 posts、work、成员、provider、轮次、事件与外键引用。遵循 [SQLite 官方通用 ALTER TABLE 流程](https://www.sqlite.org/lang_altertable.html#making_other_kinds_of_table_schema_changes)：在事务外暂时关闭本连接外键，事务内建新表/复制/替换/重建索引与触发器，执行 foreign_key_check 后提交，finally 恢复外键。失败回滚，不用 writable_schema 或改已有迁移文件。

`storage/swarm_scopes.py` 管理可信范围与旧回执对账；`storage/swarm_repository.py` 执行分域 receipt；`conversation/project_main.py` 在可信 Main 恢复时绑定匹配的历史团队；`dispatch/swarm_plans.py` 固定创建身份及人消息递送键。schema23 只在完整新运行时启用；当前已验收的 schema22 发布包不被偷偷替换。

## 验收

覆盖同名/同键两项目并行、各自 Main/成员/记忆与消息、同域冲突、跨项目/home Main 拒绝、持久恢复后的同一回执；schema22→23 前后全表身份/历史/回执对照，外键和触发器保留、故障回滚与外键恢复；旧投递回执未保存的崩溃窗口不得重复发送。使用自有 roami chrome 对真实隔离服务操作两个 OKR；受控模型不作为生产团队验收。生产维护决定仍独立，未收到答复不得绕过409。

[本批实现验收](project-scope-acceptance.md)。
