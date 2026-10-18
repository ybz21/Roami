# Agent 任务、进度、消息与提醒

## 受管任务状态

- `task_status {}` 返回当前 Main 的任务投影。用户问进度时查一次；正常等回调，不忙轮询。
- `task_cancel {taskId:ID}` 取消本用户委派任务。cancelling 不等于停止，不能据此撤回旧会话已收到的消息，更不能杀掉所有 tmux 会话。
- 原 Main 自动接收工具开始 / 结束、执行、验收与结果。状态 planned/queued/preparing/running/verifying 表示不同阶段；failed/cancelled/unknown 分开，未知不标成功，不盲目重派。
- `session_send` 只投递给旧专业会话。无生命周期回调时 executionTracked=false，投递成功不等于拿到最终结果。

## 运行时完整 CLI

下列命令供已有运行时上下文的专业执行器或终端使用。操作 ID、task/run/revision、conversation 和回报目标由实际记录获得，不编造。Main 不向自己执行 send 制造循环消息，不使用 new 创建第二个用户主对话。

```bash
roami agent status
roami agent conversations
roami agent history --conversation CONVERSATION_ID
roami agent send --conversation CONVERSATION_ID --key REQUEST_KEY --file /tmp/message.txt
roami agent steer --task TASK_ID --revision REVISION --key REQUEST_KEY --file /tmp/instruction.txt
roami agent steering --task TASK_ID --operation OPERATION_ID
roami agent report --task TASK_ID --run RUN_ID --revision REVISION --file /tmp/result.json
roami agent notify --conversation CONVERSATION_ID --source SOURCE --key DEDUPE_KEY --file /tmp/notification.txt
```

send 是用户意图输入；report 是受跟踪执行结果；notify 是主动消息，三者不互相替代。notify 要稳定 key 去重，不能用它伪造 task 成功。report 的 result JSON 使用运行时分配的协议；大段内容用文件，不在 Shell 中拼多行或密钥。steer 必须有显式当前 revision，过期时重新读状态，不偷偷更新覆盖用户的新要求。

`agent setup/init/serve --runtime-dir PATH` 是节点安装 / 初始化 / 私有 socket 服务命令，不用于日常派活。`agent new --title ...` 是兼容接口，产品 Main 使用唯一绑定，不因转交任务而调用它。

## 专业执行器生命周期

```bash
roami agent execution send-message --file /tmp/message-spec.json
roami agent execution launch --file /tmp/execution-spec.json
roami agent execution status --key LAUNCH_KEY
roami agent execution cancel --key LAUNCH_KEY
roami agent execution hook-config --executor codex
```

send-message 允许旧会话可靠投递，launch 是受跟踪任务 / 新工作区，不可互换。Spec 由宿主根据真实目标和任务记录生成；不要人工填写不存在的生命周期回调、runId 或 owner。hook-config/event/notify 由执行器集成使用；hold/reconcile-native 是工作区租约与停止证明协议，不是通用手工取消命令。

## Browser / Computer 人工接管

```bash
roami agent control ls --task TASK_ID
roami agent control show --resource RESOURCE_ID
roami agent control pause --resource RESOURCE_ID
roami agent control resume --resource RESOURCE_ID
```

pause 只有实际停止输入并释放租约后才返回 takeoverReady；pausing 时可读 show，不向用户说已经可以安全接管。resume 恢复同一资源，重新观察场景；不能复用人工操作前的旧 observationId。资源状态未知时不创建替代浏览器 / 桌面重放任务。

## 提醒与每日简报

Main 受管能力：`reminder_list {}`；`reminder_create` 带 text 并且只选一种时间：afterSeconds、whenMs、dailyAt（可附 timezone）；`reminder_cancel {id:ID}`。每日简报用 kind=daily_brief 且 dailyAt，不能同时带相对时间。模糊时间用选择题确认，不能自行添加用户未要求的定时任务。

对应完整 CLI：

```bash
roami agent reminder ls
roami agent reminder add --conversation CONVERSATION_ID --key REQUEST_KEY --text "提醒内容" --after-seconds 600
roami agent reminder add --conversation CONVERSATION_ID --key REQUEST_KEY --text "每日内容" --daily-at 09:00 --timezone Asia/Shanghai
roami agent reminder add --kind daily_brief --conversation CONVERSATION_ID --key REQUEST_KEY --text "昨日简报" --daily-at 09:00 --timezone Asia/Shanghai
roami agent reminder cancel --id REMINDER_ID
roami agent notification-preferences get
roami agent notification-preferences set --file /tmp/notification-settings.json
```

持久化 nextDueMs 只证明已排期，不证明手机收到推送；通知设置 set 替换完整对象，先 get，再保留未修改字段。取消提醒不删除已经发出的消息。
