# 指定日程的调度范围

关联 #729。

## 产品设计与用户故事

同一主机可能已有其他启用日程。用户只想让本 OKR 的原 Main 每日带原团队执行，不应因为开工而触发其他项目、新建负责人或停用别人的安排。日程仍由现有 cron 插件管理，时间选择和账号发布边界分别保留。

## 技术设计

`cron.tick` 与 `cron.serve` 增加 `--names` JSON 名称数组，或 `--name` 选择单项，精确选择已存在的日程；未传参数时保持原全局行为。`cron.list` 返回只读 `scopedScheduler=true` 能力。Scope 在任何执行前完整验证，空值/重复/不存在、互斥参数和未知选项均失败；常驻模式遇到被删除的所选任务退出，不回落全局。调度后只推进实际选中且启用到期的日程，其他行保持不变。

`plugins/cron/job-scope.go` 解析和验证范围；现有调度循环通过 `tickScoped` / `tickJobs` 保留执行记录、时间计算和失败处理。没有新增个人 crontab，也不以 action=agent 启动新实例。

启用前先用只读能力核对当前主机，再为已确认的具体时段登记 exec 日程。命令调用项目 daily-operations Skill 的原 Main wake 脚本，由宿主在事务内核对身份、空闲/等待用户状态与幂等键。当前线上旧 runtime 的预检为 supported=false，真实计划保持 disabled，不能回退普通 send 来制造唤醒成功。

## 验收

专项验证精确选择、未来/禁用任务、相似名称隔离、未知名先整体拒绝、无范围旧行为和 tick/serve 非法输入。隔离 CLI、完整质量检查和部署验收记录保留在 `/tmp/okr-scoped-scheduler-20261106/`，未执行的步骤保持待办。
