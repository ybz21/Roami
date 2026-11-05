# 日更 Skill：唤醒原 Main

关联 #656 / #658 / #679。目标是每天继续原负责人及其长期团队，不按日期新建智能体。

## Product Design

开发者先复制整套 OKR 模板；daily-operations Skill 提供开工、取数/复盘提示及 Python 唤醒脚本。
继续复用已有插件 cron 的 exec，不增加个人 crontab 或新调度守护进程。计划先禁用；用户确定
时间、时区和范围，再核对真实注册与 nextDue 后启用。页面保持现有 Main/群聊/成员入口。

唤醒是一次外部有界请求，不能当作账号、内容或发布批准。Main 自己不调用自己的唤醒脚本，
正在执行或等待用户回答时不打断。投递成功仅说明收到请求，后续仍看原成员的 task/revision/run、
真实文件和独立验收。未知结果保留同一个请求键，不创建替代者。

## User Stories

- 同项目、Main、当地日期、语义slot重放，仍是原来的一个 Main turn。
- 用户开始聊天后，日程不能靠较早的只读检查打断它；宿主在写事务内复核。
- 首页Main、其他项目、成员和已删除对话不作为本项目日程目标。
- 两个机器时区不同，排期仍按确认的IANA时区；编辑任务不丢原时区、不顺手启用。
- 旧服务缺少唤醒能力时只能预览/报告不支持，不能回退普通send或新建会话。

## Technical Design

`roami agent identity`读取已有私有身份API。`roami agent wake`显式携带项目/Main/key，并拒绝
原生智能体shell的误调用；标记仅限制误用，不授予身份。Go公共路由仍走已有登录边界。

Python `ConversationService.wake_project`调用`Conversations.accept(wake_project=...)`：同一事务
核对owner、project_main和项目绑定，复用同内容请求回执；新请求再检查active branch无queued/running
turn、无未答question，然后提交一个turn和job。它不调用普通submit的preempt，不学习成新的用户偏好，
消息执行记录保留scheduled来源；普通聊天及旧请求digest保持兼容。请求身份冲突与payload变化拒绝。

模板`scripts/wake_main.py`只用标准库和已安装CLI，先检查projectMainWake能力、身份与当前分支。
日期由确认时区生成；requestKey由project/Main/date/slot生成，提示改动不产生第二个键。
正文经stdin发送，argv不走shell。prepared/deferred/accepted/unknown分别记载，不声称完成。
新端点不存在时不会退回普通send。脚本不直接执行Connector、不保存已确认指标、不发布。

cron新增creation-only enabled选项及timezone；省略enabled保持旧新建默认，编辑保持原状态。
未传timezone的旧表单编辑继承原值，显式改变启停仍走enable/disable。nextRun和preview使用同一时区；
原server-local任务不改变。每个slot独立注册，重复触发同日/slot只会收到原回执。

## Acceptance

专项覆盖并发八次只创建一个原Main消息/turn/job、不同正文冲突、普通用户请求优先、继承分支的未答
问题、owner/首页/其他项目/普通对话/未知字段隔离，以及模板跨当地日去重、旧服务只读准备、调用结果未知。
Go验证真实CLI到私有Unix HTTP身份入口；插件验证禁用创建、编辑保留时区、显式启停不被编辑绕过和DST。
完整门禁、隔离CLI联验与受控实际触发在交付记录补录。当前模型400和运行时升级准入阻塞仍保留，
未把离线专项或脚本存在当成每日机制已在线，未启用真实宣传日程或操作手机。
