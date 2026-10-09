package agentdiscovery

import (
	"ttmux-cli-go/pkg/plugin/manifest"
	"ttmux-cli-go/pkg/plugin/sdk"
)

func init() { sdk.RegisterBuiltin(Manifest(), Activate) }

func Manifest() manifest.Manifest {
	return manifest.Manifest{
		ManifestVersion: 1, ID: "roam.agent-discovery", Publisher: "roam", Name: "agent-discovery",
		DisplayName:      manifest.LocaleText{"zh-CN": "Agent 发现", "en-US": "Agent Discovery"},
		Version:          "0.1.0",
		Description:      manifest.LocaleText{"zh-CN": "发现本机 Agent、安装 CLI，并显示可用的额度快照", "en-US": "Discover local agents, install CLIs, and show available quota snapshots"},
		Runtime:          manifest.Runtime{Kind: "builtin"},
		Permissions:      manifest.Perms{Commands: manifest.CommandPerms{Allow: []string{"npm install -g"}}},
		ActivationEvents: []string{"onCommand:agent-discovery.scan", "onCommand:agent-discovery.install"},
		Contributes: manifest.Contribs{Commands: []manifest.CommandContrib{
			{ID: "agent-discovery.scan", Title: manifest.LocaleText{"zh-CN": "扫描本机 Agent", "en-US": "Scan local agents"}},
			{ID: "agent-discovery.install", Title: manifest.LocaleText{"zh-CN": "安装 Agent CLI", "en-US": "Install agent CLI"}},
		}},
	}
}
