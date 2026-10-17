// 自注册:manifest 与实现同住本包,import 即生效(见 sdk.RegisterBuiltin)。
package im

import (
	"github.com/ybz21/Roami/pkg/plugin/manifest"
	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

func init() { sdk.RegisterBuiltin(Manifest(), Activate) }

// Manifest declares the plugin (docs/design/plugin/05-manifest.md).
func Manifest() manifest.Manifest {
	return manifest.Manifest{
		ManifestVersion: 1,
		ID:              "roam.im-bridge",
		Publisher:       "roam",
		Name:            "im-bridge",
		DisplayName:     manifest.LocaleText{"zh-CN": "IM 机器人", "en-US": "IM Bridge"},
		Version:         "0.4.0",
		Description: manifest.LocaleText{
			"zh-CN": "双向 IM 桥(飞书已支持,钉钉等可扩展):@机器人 的消息进常驻管家 Agent,简单问题直接答,复杂任务委派 worker 会话干活并回报;Roami 通知推送到绑定的群",
			"en-US": "Two-way IM bridge (Feishu supported, DingTalk extensible): messages go to a resident concierge agent that answers directly or delegates worker sessions; Roami notifications go to the bound chat",
		},
		Runtime: manifest.Runtime{Kind: "builtin"},
		Permissions: manifest.Perms{
			Notifications: []string{"subscribe"},
			// 入站派活:@机器人 的消息进常驻管家会话,由它委派 worker
			Agents: []string{"spawn"},
			// write 为高危能力:listener 向管家会话投递收件通知(session.send)、
			// graceful recycle 收会话(session.kill,仅限本插件会话)都要它;
			// 每次调用均过宿主审计日志
			Sessions: []string{"read", "write"},
			Network:  manifest.NetworkPerms{AllowedDomains: []string{"https://open.feishu.cn"}},
			Secrets:  []string{"app_secret"},
		},
		ActivationEvents: []string{
			"onNotification:*",
			"onCommand:im-bridge.test",
			"onCommand:im-bridge.listen",
		},
		Contributes: manifest.Contribs{
			Commands: []manifest.CommandContrib{
				{ID: "im-bridge.test", Title: manifest.LocaleText{"zh-CN": "发送测试卡片", "en-US": "Send test card"}},
				{ID: "im-bridge.listen", Title: manifest.LocaleText{"zh-CN": "长连接监听 @机器人(plugind 自动托管)", "en-US": "Listen for @bot messages (managed by plugind)"}},
				{ID: "im-bridge.send", Title: manifest.LocaleText{"zh-CN": "发消息到飞书会话(派活 Agent 的汇报通道)", "en-US": "Send a message to a Feishu chat (agent reporting channel)"}},
				{ID: "im-bridge.bind-token", Title: manifest.LocaleText{"zh-CN": "生成 owner 绑定口令(10 分钟有效)", "en-US": "Generate an owner bind token (valid 10 min)"}},
				{ID: "im-bridge.delegate", Title: manifest.LocaleText{"zh-CN": "委派 worker 会话(管家的打包派活命令)", "en-US": "Delegate a worker session (concierge's packaged dispatch)"}},
			},
			NotificationSinks: []manifest.SinkContrib{
				{ID: "feishu.send", Events: []string{"finding.blocking", "review.completed", "monitor.alert", "*"}},
			},
			ConfigGroups: []manifest.ConfigGroup{
				{Key: "inbound",
					Title: manifest.LocaleText{"zh-CN": "飞书自建应用(provider=feishu)", "en-US": "Feishu self-built app (provider=feishu)"},
					Description: manifest.LocaleText{
						"zh-CN": "配好后群里 @应用机器人 即可查状态、派活给 Agent、干完回报;再说一句「绑定通知」,Roami 系统通知(互审结果、告警)也发到该群。\n1. open.feishu.cn → 创建「企业自建应用」,取 App ID / App Secret\n2. 权限管理:开通 im:message(获取与发送单聊、群组消息)\n3. 事件订阅:选「使用长连接接收事件」,订阅「接收消息 im.message.receive_v1」\n4. 发布版本,把应用机器人拉进群\n5. 保存后 plugind 自动拉起监听(tmux 会话 _ttmux-im),群里 @它 说「帮助」验证",
						"en-US": "Once configured, @ the app bot in a group to check status, dispatch agent tasks and get results back; say \"bind\" and Roami system notifications also go to that chat.\n1. open.feishu.cn → create a self-built app, get App ID / App Secret\n2. Scopes: enable im:message (receive & send)\n3. Events: choose long-connection mode, subscribe to im.message.receive_v1\n4. Release the app and add its bot to the group\n5. Save; plugind auto-starts the listener (tmux session _ttmux-im) — @ the bot with \"help\" to verify"},
				},
				{Key: "task",
					Title: manifest.LocaleText{"zh-CN": "派活设置", "en-US": "Task settings"},
					Description: manifest.LocaleText{
						"zh-CN": "@机器人 的非指令文本会变成一次性 Agent 会话,干完把结果卡片发回群。",
						"en-US": "Non-command @bot messages become one-shot agent sessions; results are posted back to the chat."},
				},
			},
			ConfigFields: []manifest.ConfigField{
				{Key: "im_provider",
					Title:       manifest.LocaleText{"zh-CN": "IM 提供方", "en-US": "IM provider"},
					Description: manifest.LocaleText{"zh-CN": "留空=feishu;dingtalk 为预留扩展位(尚未实现)", "en-US": "Empty = feishu; dingtalk is a reserved extension (not implemented yet)"},
					Options:     []string{"", "feishu", "dingtalk"}},
				{Key: "app_id", Group: "inbound",
					Title:       manifest.LocaleText{"zh-CN": "App ID", "en-US": "App ID"},
					Placeholder: "cli_xxxxxxxxxxxxxxxx"},
				{Key: "app_secret", Group: "inbound", Secret: true,
					Title: manifest.LocaleText{"zh-CN": "App Secret", "en-US": "App Secret"}},
				{Key: "notify_chat", Group: "inbound",
					Title:       manifest.LocaleText{"zh-CN": "通知群 chat_id", "en-US": "Notification chat_id"},
					Description: manifest.LocaleText{"zh-CN": "系统通知发到哪个群;一般不用手填——群里 @机器人 说「绑定通知」会自动记录", "en-US": "Target chat for system notifications; usually auto-set by @bot \"bind\" in the group"},
					Placeholder: "oc_xxxxxxxx(可留空,由「绑定通知」自动记录)"},
				{Key: "workdir", Group: "task",
					Title:       manifest.LocaleText{"zh-CN": "默认工作目录", "en-US": "Default workdir"},
					Description: manifest.LocaleText{"zh-CN": "派下来的任务在哪个目录干活;留空用家目录", "en-US": "Where dispatched tasks run; empty = home dir"},
					Placeholder: "/home/you/codes/xxx"},
				{Key: "provider", Group: "task",
					Title:       manifest.LocaleText{"zh-CN": "执行 Agent", "en-US": "Agent"},
					Description: manifest.LocaleText{"zh-CN": "留空用 claude", "en-US": "Empty = claude"},
					Options:     []string{"", "claude", "codex"}},
				{Key: "task_mode", Group: "task",
					Title:       manifest.LocaleText{"zh-CN": "任务模式", "en-US": "Task mode"},
					Description: manifest.LocaleText{"zh-CN": "留空=concierge:常驻管家接管全部消息,自答或委派 worker;interactive:每任务一个 Agent 会话;oneshot:一次性跑完,日志截尾回报", "en-US": "Empty = concierge: a resident agent handles all messages, answering or delegating workers; interactive: one agent session per task; oneshot: run once and report the log tail"},
					Options:     []string{"", "concierge", "interactive", "oneshot"}},
				{Key: "workspace", Group: "task",
					Title:       manifest.LocaleText{"zh-CN": "管家工作目录", "en-US": "Concierge workspace"},
					Description: manifest.LocaleText{"zh-CN": "常驻管家的家:AGENT.md(角色与协议,可自行修改)、MEMORY.md、tasks/ 台账、inbox.jsonl 收件箱都在这里", "en-US": "Home of the resident concierge: AGENT.md (role & protocol, editable), MEMORY.md, tasks/ ledger and inbox.jsonl live here"},
					Placeholder: "~/.roami/plugins/feishu/workspace"},
				{Key: "tick_interval", Group: "task",
					Title:       manifest.LocaleText{"zh-CN": "心跳巡逻间隔", "en-US": "Patrol tick interval"},
					Description: manifest.LocaleText{"zh-CN": "每隔这么久给管家投一次 tick,它会巡检超时 worker、跟进悬置事项;如 10m/30m,填 off 关闭", "en-US": "Interval between patrol ticks (e.g. 10m/30m); the concierge checks stalled workers and pending items; 'off' disables"},
					Placeholder: "10m"},
				{Key: "recycle_at", Group: "task",
					Title:       manifest.LocaleText{"zh-CN": "每日重建时刻", "en-US": "Daily recycle time"},
					Description: manifest.LocaleText{"zh-CN": "HH:MM(如 04:00)优雅重建管家会话防上下文膨胀:先通知写 checkpoint、等空闲再收;留空不自动重建", "en-US": "HH:MM (e.g. 04:00) to gracefully rebuild the concierge (checkpoint → idle → recycle); empty disables"},
					Placeholder: "04:00"},
				{Key: "owner_open_id", Group: "inbound",
					Title:       manifest.LocaleText{"zh-CN": "Owner open_id", "en-US": "Owner open_id"},
					Description: manifest.LocaleText{"zh-CN": "唯一能指挥管家的主人;推荐经绑定流程自动写入:本机执行 roami plugin run im-bridge.bind-token 拿一次性口令,再在飞书里说「绑定通知 <口令>」", "en-US": "The only user who commands the concierge; prefer the bind flow: run im-bridge.bind-token locally, then say \"绑定通知 <token>\" in Feishu"},
					Placeholder: "ou_xxxxxxxx"},
				{Key: "allow_users", Group: "inbound",
					Title:       manifest.LocaleText{"zh-CN": "额外允许的用户", "en-US": "Additional allowed users"},
					Description: manifest.LocaleText{"zh-CN": "除 owner 外可指挥管家的用户 open_id,逗号分隔;其他人 @机器人 会被拒绝", "en-US": "open_ids (comma-separated) allowed besides the owner; anyone else is refused"},
					Placeholder: "ou_aaa,ou_bbb"},
				{Key: "allow_chats", Group: "inbound",
					Title:       manifest.LocaleText{"zh-CN": "允许的会话", "en-US": "Allowed chats"},
					Description: manifest.LocaleText{"zh-CN": "限定只在这些 chat_id 里响应(逗号分隔);留空=不按会话限制(仍按用户白名单校验)", "en-US": "Restrict to these chat_ids (comma-separated); empty = no chat restriction (user whitelist still applies)"},
					Placeholder: "oc_xxx,oc_yyy"},
			},
		},
	}
}
