// builtin 插件自注册:插件包在 init() 里带着自己的 manifest 报到,宿主
// (internal/plugin/builtin)只 blank-import 插件包即可拿到全量注册表——
// 新增插件不再改宿主代码(导入行与 go.mod 由
// scripts/dev/gen-builtin-plugins.sh 扫 plugins/ 目录生成)。
package sdk

import (
	"fmt"

	"github.com/ybz21/Roami/pkg/plugin/manifest"
)

// Builtin pairs a manifest with its activation entry.
type Builtin struct {
	Manifest manifest.Manifest
	Activate func(ctx *Ctx) Plugin
}

var builtins []Builtin

// RegisterBuiltin 供插件包 init() 调用。id 重复或 manifest 非法直接 panic:
// 注册发生在进程启动最早期,响亮地挂掉比带病注册好定位。
func RegisterBuiltin(m manifest.Manifest, activate func(ctx *Ctx) Plugin) {
	if err := m.Validate(); err != nil {
		panic(fmt.Sprintf("sdk: invalid builtin manifest: %v", err))
	}
	if activate == nil {
		panic(fmt.Sprintf("sdk: builtin %s registered without Activate", m.ID))
	}
	for _, b := range builtins {
		if b.Manifest.ID == m.ID {
			panic(fmt.Sprintf("sdk: builtin %s registered twice", m.ID))
		}
	}
	builtins = append(builtins, Builtin{Manifest: m, Activate: activate})
}

// Builtins returns all self-registered builtin plugins (注册顺序 = 导入顺序).
func Builtins() []Builtin {
	out := make([]Builtin, len(builtins))
	copy(out, builtins)
	return out
}
