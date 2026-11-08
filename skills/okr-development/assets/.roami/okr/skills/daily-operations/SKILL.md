---
name: daily-operations
description: 通过已确认日程唤醒本项目的原持续目标，复用 Main 和团队继续执行。
---

由开发终端或既有调度插件调用，Main 不运行外部脚本唤醒自己。

先核对项目、Main、Swarm 与仍有效的 delegationId。持续目标由原 Main 在真实用户回合启用；
日程和成员消息不产生新授权。没有有效目标时在原 Main 处理真实用户要求，不建立替代会话，
不回退普通 send 或 message wake。

在项目根执行，调度命令使用同一项目根或绝对路径：

```bash
daily_skill_dir=".roami/okr/skills/daily-operations"
python3 "$daily_skill_dir/scripts/wake_main.py" --project "$project_id" --conversation "$main_id" \
  --swarm "$swarm_id" --delegation "$delegation_id" --timezone "$timezone" --slot kickoff --dry-run
```

脚本核对 projectGoalDailyWake 和项目 Main 身份，再调用 roami swarm daily。宿主再次核对
owner、项目、原 Main、原目标和用户来源；dry-run 不保存通知。旧运行时仅有 projectMainWake
不够，脚本停止，不用旧消息入口替代。去掉 dry-run 后 accepted 仅表示通知已保存，不表示
Main 已开始、成员已执行或发布成功。

日期槽按 delegationId、IANA 时区、本地日期和 slot 去重。Main 忙或等待用户回答时保留通知，
不打断对话；暂停后可以恢复。目标撤销、来源停止或遗忘、团队归档后不执行。已过本地日期的
通知或未开始的协调回合不自动补跑；已开始的真实工作保留执行状态。夏令时重复的一小时沿用
同一本地日期槽，不随机换 slot 绕过去重。

超时或 unknown 时保留回执里的原日期及身份，先核对原通知；重试用 --date YYYY-MM-DD
传原日期，不把未知的昨天滚成今天。宿主拒绝过期或未来日期。要改变工作，交原 Main 续派，
不通过日程正文另造任务。prompts/ 是 Main 阅读的工作说明，不作为新用户消息发送。

使用既有 cron 的 action=exec 调用脚本。创建提案显式 enabled=false 并填 IANA timezone，
核对用户已确认的时间、范围、运行者、命令和 nextRun 后再启用；编辑保留原启停和时区。
先查询实际插件 help/schema，不臆造注册命令。模板 schedules/daily.json 不是调度注册回执。
不使用每次新建会话的 action=agent，不加个人 crontab，不为本项目启动其他任务的日程。

先受控触发核对原 Main 日期槽、turn、原成员 task/revision/run 和独立验收，再核对下一次
真实定时的 lastRun、结果和 nextRun。脚本不执行 Connector、不冻结内容或发布，不修改任务
状态、路由和费用；取数与发布由原团队按实际能力和原目标范围执行。
