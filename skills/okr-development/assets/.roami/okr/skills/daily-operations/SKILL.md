---
name: daily-operations
description: 配置已有项目 Main 的日更唤醒，继续原团队的开工、取数与复盘。
---

由开发终端或既有调度插件调用；Main 消费请求并继续指挥原成员，不运行脚本唤醒自己。

先读本项目与团队的真实绑定，取得已存在的 Main conversationId；不要根据名称或目录猜测。
选用 `prompts/kickoff.md`、`prompts/review.md`，按用户确认的职责、口径和执行范围修改。

在项目根目录执行；调度命令使用同一项目根或这些文件的绝对路径。

```bash
daily_skill_dir=".roami/okr/skills/daily-operations"
python3 "$daily_skill_dir/scripts/wake_main.py" --project "$project_id" --conversation "$main_id" \
  --timezone "$timezone" --slot kickoff --prompt-file "$daily_skill_dir/prompts/kickoff.md" --dry-run
```

脚本通过 `roami agent identity` 核对原项目 Main，读取当前分支，并检查 projectMainWake 能力。
实际投递使用 project-scoped wake，宿主在同一事务再次核对身份与空闲状态；遇到正在执行或等待用户回答
则推迟；dry-run 只读。去掉 dry-run 才投递，返回 accepted 仅代表请求已接收，不能算成员执行、
Connector 取数或发布成功。旧运行时的 dry-run 会返回 supported=false；实际触发停止，不回退普通 send、首页 Main 或创建新对话。

使用既有 cron 的 exec 调用同一条脚本命令。以 `cron.add --enabled false --timezone <IANA时区>` 创建禁用计划，确认时间/时区、目标、权限和
下次触发，再用 cron.enable 启用；新任务未传 enabled 时仍默认启用，不能先 add 再 disable 冒充安全准备。
编辑已有任务保留原启停与未指定的时区，不靠默认值重置。
启用安排由操作者按当前插件实际能力完成；模板 schedules/daily.json 不是已注册调度。

同项目/Main/当地日期/slot 复用原 requestKey；重复调用不创建第二条请求。unknown 时先查
原 Main 与回执，不换键，不改正文盲目重投。要改本日已投递工作，交 Main 继续原任务。
每日可配置多个语义 slot，但不能随机改 slot 绕过去重。

先做一次获授权的受控触发，核对原 Main 的实际 turn、后续原成员 task/revision/run、文件及
独立验收；再验证下一次真实定时。脚本本身不执行 Connector、不批准账号/内容、不发布、
不改任务状态、路由或费用。调度进程和主机需持续在线，关闭客户端不会代替调度服务。
