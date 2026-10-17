// 品牌从 Roami 改成 Roami 之后的环境变量兼容层。
//
// 改名不该逼几十个 os.Getenv("ROAM_…") 的读取点跟着改一遍，更不该让别人脚本里、
// systemd unit 里、.env 里已经写好的 ROAM_WEB_PASSWORD 突然失灵。
// 所以只在进程起来时做一次桥接：ROAMI_X 与 ROAM_X 互为别名，谁写了算谁，
// 两个都写以新名（ROAMI_）为准。读取点一行都不用动。
package runtime

import (
	"os"
	"strings"
)

const (
	newPrefix = "ROAMI_"
	oldPrefix = "ROAM_"
)

// BridgeEnvAliases 把 ROAMI_* 与 ROAM_* 互补齐。幂等，进程启动时调一次。
func BridgeEnvAliases() {
	for _, kv := range os.Environ() {
		key, val, ok := strings.Cut(kv, "=")
		if !ok || val == "" {
			continue
		}
		switch {
		case strings.HasPrefix(key, newPrefix):
			if old := oldPrefix + strings.TrimPrefix(key, newPrefix); os.Getenv(old) == "" {
				_ = os.Setenv(old, val)
			}
		case strings.HasPrefix(key, oldPrefix):
			if nw := newPrefix + strings.TrimPrefix(key, oldPrefix); os.Getenv(nw) == "" {
				_ = os.Setenv(nw, val)
			}
		}
	}
}
