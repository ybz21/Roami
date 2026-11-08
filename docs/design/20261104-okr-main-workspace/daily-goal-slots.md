# 原目标每日唤醒

## Product Design

项目的 daily-operations Skill 通过已有 cron 的 exec 触发原持续目标，复用原 Main 和成员。
日程只提交一个日期槽，不添加新的用户消息，也不授予发布资格。项目定义、Connector、审核与
实际外部动作仍由原团队按真实能力执行。

## User Stories

- 同一本地日期和时段重复触发时，看到同一个通知和协调回合。
- Main 忙或等待用户回答时保留通知，不中断对话；暂停后可在当天恢复。
- 已撤销、停止、遗忘或归档的目标不继续执行，过期日期不在次日补跑。
- 从完整初始化模板复制项目后，直接使用其中的 Skill 脚本和手册，不自建替代指挥会话。

## Technical Design

Python 宿主提供 POST `/v1/swarms/{sid}/goal/daily`，校验 owner、原项目、原 Main、有效
delegation、时区、本地日期和 slot；schema 不接收新指令。`/v1/status` 单独声明
`projectGoalDailyWake`，旧的普通消息 wake 能力不能替代它。

Go CLI 的 `roami swarm daily` 负责实际 UDS 调用。项目 Skill 先核对能力和 Main 身份，再携带
原目标和明确日期调用；超时保留原身份，不自动重试。恢复使用原 `--date`，过期或未来日期
由宿主拒绝，不把昨天的未知投递滚成今天。dry-run 不入队。

`storage/swarm_daily_goal.py` 在现有 jobs 表按 delegationId、IANA 时区、本地日期、slot
派生稳定键。生产通知与当前目标检查同事务进行；处理通知时再次验证来源，再同事务创建原
Main 的协调 batch 与 turn.run。复用 Scheduler 的 control 池，没有新轮询器或数据库迁移。

`swarm_coordination` 在实际 turn.run payload、admitted batch、prompt manifest 中保留
dailySlot；和首次 initialGoal、成员回执分别记录来源。通知处理和首次 mailbox claim 都检查
日期。已经开始的真实工作不因午夜被丢弃；未开始的旧日期回合留下 interrupted 事实。

模板同时更新脚本、Skill、Main 声明、两份初始化 AGENTS 和 daily-loop 手册；package.files
按当前完整目录重算，保留 #786 已合入的 Main/Swarm 指引。日程需使用本项目约定的时间、时区、
范围和运行者，核对 nextRun/lastRun；模板 daily.json 和 accepted 回执都不是实际日程运行证据。

同一 Main 在协调回合读取项目时，复用[项目只读入口](coordination-project-context.md)的范围校验。
配置写入、原始 shell、发布权限仍不由日期槽放开。

## 验收边界

### 同目录成员排队

X、Bili 和数据成员可以有不同 workspaceId，但仍指向同一项目目录。调度器以已解析的
nodeId 与实际目录作为资源键，本机目录解析符号链接。当前 revision 的 preparing/running/
cancelling 执行和尚未结束的调度 handle 保留资源；CLI 提交返回后也由持久任务状态继续占用。
冲突的原 job 留在队列，不制造失败、不新建成员、不换任务身份。不同目录仍可并行。

尚未解析目录的活跃准备任务短暂阻止新的 task.run，解析完成后按真实目录放行；历史残留的
未知目录记录不形成全局锁。Main、回执与审核继续处理。这里只减少可预期的占用冲突，Go 的
目录围栏仍是执行授权依据；未知执行结果不会被清理或改成已知。验收覆盖原 job 保留、CLI
脱离 handle 后占用、不同 workspaceId/符号链接、不同目录并行及旧 busy 记录保留。

隔离草稿通过 141 项运行时联动、21 项模板检查，以及真实模板 Skill→Go CLI→Python UDS→原
Main 完整路径；包含重复触发、无新用户消息、无新成员、暂停/撤销/归档、跨日和事务回滚。
当前工作区集成后重新验证，不能把旧草稿结果当本提交的最终完整门禁。

尚未登记生产 cron、连接发布账号或完成两轮真实发布/取数/看板/复盘；本实现不把这些列为完成。
