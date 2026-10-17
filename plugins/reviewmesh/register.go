// 自注册:manifest 与实现同住本包,import 即生效(见 sdk.RegisterBuiltin)。
package reviewmesh

import (
	"github.com/ybz21/Roami/pkg/plugin/manifest"
	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

func init() { sdk.RegisterBuiltin(Manifest(), Activate) }

// Manifest declares the plugin (docs/design/plugin/05-manifest.md).
func Manifest() manifest.Manifest {
	return manifest.Manifest{
		ManifestVersion: 1,
		ID:              "roam.review-mesh",
		Publisher:       "roam",
		Name:            "review-mesh",
		DisplayName:     manifest.LocaleText{"zh-CN": "智能互审", "en-US": "Review Mesh"},
		Version:         "0.1.0",
		Description: manifest.LocaleText{
			"zh-CN": "对当前工作区变更拉起 reviewer Agent(codex/claude),产出结构化 finding 并发布通知",
			"en-US": "Peer-review the current diff with a reviewer agent, producing structured findings",
		},
		Runtime: manifest.Runtime{Kind: "builtin"},
		Permissions: manifest.Perms{
			Workspace: []string{"read"},
			Agents:    []string{"spawn"},
			// write:互审意见回灌开发会话(session.send),高危已声明
			Sessions:      []string{"read", "write"},
			Findings:      []string{"read", "write"},
			Notifications: []string{"publish"},
		},
		ActivationEvents: []string{
			"onCommand:review-mesh.review",
			"onCommand:review-mesh.status",
			"onCommand:review-mesh.watch",
		},
		Contributes: manifest.Contribs{
			Commands: []manifest.CommandContrib{
				{ID: "review-mesh.review", Title: manifest.LocaleText{"zh-CN": "互审当前变更", "en-US": "Review current changes"}},
				{ID: "review-mesh.status", Title: manifest.LocaleText{"zh-CN": "互审状态", "en-US": "Review status"}},
				{ID: "review-mesh.watch", Title: manifest.LocaleText{"zh-CN": "陪跑监控会话(空闲即互审)", "en-US": "Watch a session (review on idle)"}},
			},
			ConfigFields: []manifest.ConfigField{
				{Key: "provider",
					Title:       manifest.LocaleText{"zh-CN": "默认评审 Agent", "en-US": "Default reviewer agent"},
					Description: manifest.LocaleText{"zh-CN": "留空则自动选择(codex 优先)", "en-US": "Empty = auto (prefer codex)"},
					Options:     []string{"", "codex", "claude"}},
				{Key: "rounds",
					Title:       manifest.LocaleText{"zh-CN": "自动互审轮次上限", "en-US": "Max auto-review rounds"},
					Description: manifest.LocaleText{"zh-CN": "陪跑时同一会话最多自动互审几轮(留空=3,上限 20);单次可用 --rounds 覆盖", "en-US": "Max auto-review rounds per watched session (empty = 3, cap 20); override per run with --rounds"},
					Placeholder: "3"},
			},
		},
	}
}
