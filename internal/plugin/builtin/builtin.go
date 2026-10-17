// Package builtin wires the official builtin plugins (Go 实现,编译进 ttmux
// 单二进制,由隐藏子命令 _plugin-host 以子进程 + stdio JSON-RPC 拉起,与第三
// 方插件走完全相同的协议;见 docs/design/plugin/04 第 3 节)。
//
// 插件自注册:每个插件包在 init() 里 sdk.RegisterBuiltin(manifest, Activate),
// 本包只负责 blank-import 插件包(imports_gen.go,由
// scripts/dev/gen-builtin-plugins.sh 扫 plugins/ 目录生成)并把注册表转交
// 宿主——新增插件零手改 CLI 代码。
package builtin

import (
	"github.com/ybz21/Roami/internal/plugin"
	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

// Builtin pairs a manifest with its activation entry.
type Builtin = sdk.Builtin

func init() {
	for _, b := range All() {
		plugin.RegisterBuiltinManifest(b.Manifest)
	}
}

// All returns every self-registered builtin plugin.
func All() []Builtin { return sdk.Builtins() }

// Find resolves a builtin by full id.
func Find(id string) (Builtin, bool) {
	for _, b := range All() {
		if b.Manifest.ID == id {
			return b, true
		}
	}
	return Builtin{}, false
}
