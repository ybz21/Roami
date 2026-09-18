// 自注册:manifest 与实现同住本包,import 即生效(见 sdk.RegisterBuiltin)。
package keepalive

import (
	"ttmux-cli-go/pkg/plugin/manifest"
	"ttmux-cli-go/pkg/plugin/sdk"
)

func init() { sdk.RegisterBuiltin(Manifest(), Activate) }

// Manifest declares the plugin (docs/design/plugin/05-manifest.md).
//
// 定位:替人「看着」那些会话。Agent 干着干着停下来等一句话是常态——它没死,
// 只是在等;而你可能几个小时后才发现。本插件按会话记一张守护表,发现某个会话
// 安静得太久就替你说一句(默认「继续」),把它推回去接着干。
//
// 没有配置项走 manifest 的 configFields:全局默认(守护语、安静多久算停住、
// 两次催促的最小间隔)和逐会话的开关是同一件事的两层,拆到「配置」页和面板
// 两处填,人就得在两个地方来回对。全部收在插件面板里,落插件私有 storage,
// 常驻循环每轮重读——改一句守护语,下一轮就生效,不用重启循环。
func Manifest() manifest.Manifest {
	return manifest.Manifest{
		ManifestVersion: 1,
		ID:              "roam.keepalive",
		Publisher:       "roam",
		Name:            "keepalive",
		DisplayName:     manifest.LocaleText{"zh-CN": "会话守护", "en-US": "Keepalive"},
		Version:         "0.1.0",
		Description: manifest.LocaleText{
			"zh-CN": "替你看着会话:挑几个会话守着,谁安静太久就自动催一句把它推回去干活(说什么按屏幕上看见的分叉,断线那种会让它接着上次说);连催几次没反应就停手并通知你。默认一个会话都不守,开关得你亲手打开",
			"en-US": "Watches your sessions: nudge any guarded session that has been quiet for too long, picking what to say from an ordered rule table (a dropped request gets \"resume where you left off\", not \"continue\"); stop plus notify when several nudges in a row get no response. Nothing is guarded until you switch it on",
		},
		Runtime: manifest.Runtime{Kind: "builtin", Resident: true},
		Permissions: manifest.Perms{
			// read:列会话、看屏幕(判断还动不动);write:发那句守护语。
			Sessions:      []string{"read", "write"},
			Notifications: []string{"publish"},
		},
		ActivationEvents: []string{
			"onCommand:keepalive.list", "onCommand:keepalive.on", "onCommand:keepalive.off",
			"onCommand:keepalive.all", "onCommand:keepalive.settings", "onCommand:keepalive.rules",
			"onCommand:keepalive.dryrun", "onCommand:keepalive.ping",
			"onCommand:keepalive.history", "onCommand:keepalive.tick", "onCommand:keepalive.serve",
		},
		Contributes: manifest.Contribs{
			Commands: []manifest.CommandContrib{
				{ID: "keepalive.list", Title: manifest.LocaleText{"zh-CN": "列出所有会话与各自的守护状态", "en-US": "List all sessions and their guard state"}},
				{ID: "keepalive.on", Title: manifest.LocaleText{"zh-CN": "开始守护一个会话", "en-US": "Start guarding a session"}},
				{ID: "keepalive.off", Title: manifest.LocaleText{"zh-CN": "停止守护一个会话", "en-US": "Stop guarding a session"}},
				{ID: "keepalive.all", Title: manifest.LocaleText{"zh-CN": "一键守护/取消全部会话", "en-US": "Guard or release every session at once"}},
				{ID: "keepalive.settings", Title: manifest.LocaleText{"zh-CN": "读取或修改全局默认(兜底守护语、间隔)", "en-US": "Read or update the global defaults"}},
				{ID: "keepalive.rules", Title: manifest.LocaleText{"zh-CN": "读取或覆写守护语规则表(屏幕上出现什么就说哪句)", "en-US": "Read or replace the nudge rule table"}},
				{ID: "keepalive.dryrun", Title: manifest.LocaleText{"zh-CN": "拿某个会话此刻的屏幕试一遍规则(不发送)", "en-US": "Dry-run the rules against a session's current screen"}},
				{ID: "keepalive.ping", Title: manifest.LocaleText{"zh-CN": "立刻对一个会话发一次守护语", "en-US": "Nudge a session right now"}},
				{ID: "keepalive.history", Title: manifest.LocaleText{"zh-CN": "查看发送记录(发给谁、发了什么、当时安静多久)", "en-US": "Show the nudge history"}},
				{ID: "keepalive.tick", Title: manifest.LocaleText{"zh-CN": "巡检一次并催醒所有该催的会话", "en-US": "Run one sweep and nudge every due session"}},
				{ID: "keepalive.serve", Title: manifest.LocaleText{"zh-CN": "常驻守护循环(由 plugind 自动拉起)", "en-US": "Resident guard loop (started by plugind)"}},
			},
		},
	}
}
