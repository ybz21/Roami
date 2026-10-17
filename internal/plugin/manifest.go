// Package plugin implements the Roami plugin foundation (设计见
// docs/design/plugin/):manifest、注册表、宿主 API、插件子进程托管与守护进程。
//
// v0 范围(对应设计文档 MVP-A/B 切片):builtin(Go)插件、commands 与
// notificationSinks 贡献点、workspace/agent/session/command/finding/
// notification 平台 API、命令白名单强制、审计。MCP 桥、node/exec 运行时、
// webhook、事件日志分库为后续增量。
//
// manifest 模型本体在公开包 pkg/plugin/manifest(builtin 插件自声明所需),
// 这里经类型别名复用,宿主代码不感知搬迁。
package plugin

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/ybz21/Roami/pkg/plugin/manifest"
)

type (
	LocaleText     = manifest.LocaleText
	Manifest       = manifest.Manifest
	Runtime        = manifest.Runtime
	Perms          = manifest.Perms
	CommandPerms   = manifest.CommandPerms
	NetworkPerms   = manifest.NetworkPerms
	Contribs       = manifest.Contribs
	ConfigGroup    = manifest.ConfigGroup
	ConfigField    = manifest.ConfigField
	CommandContrib = manifest.CommandContrib
	SinkContrib    = manifest.SinkContrib
)

// ParseManifestFile loads and validates a roam-plugin.json from dir.
func ParseManifestFile(dir string) (Manifest, error) {
	var m Manifest
	b, err := os.ReadFile(filepath.Join(dir, "roam-plugin.json"))
	if err != nil {
		return m, err
	}
	if err := json.Unmarshal(b, &m); err != nil {
		return m, fmt.Errorf("roam-plugin.json: %w", err)
	}
	return m, m.Validate()
}
