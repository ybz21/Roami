// 品牌从 Roami 改成 Roami 之后的环境变量兼容层。
//
// 改名不该逼几十个 os.Getenv("ROAM_…") 的读取点跟着改一遍，更不该让别人脚本里、
// systemd unit 里、.env 里已经写好的 ROAM_WEB_PASSWORD 突然失灵。
// 只在进程起来时做一次桥接：ROAMI_X 与 ROAM_X 互为别名，谁写了算谁，
// 两个都写以新名（ROAMI_）为准。读取点一行都不用动。
//
// CLI 那边有一份一模一样的（cli/github.com/ybz21/Roami/internal/tmuxruntime/envalias.go）：
// backend 与 cli 是两个独立 go module，为二十行代码拉一个共享 module 不划算——
// 改动时两边一起改。
package config

import (
	"os"
	"strings"
)

const (
	newEnvPrefix = "ROAMI_"
	oldEnvPrefix = "ROAM_"
)

// BridgeEnvAliases 把 ROAMI_* 与 ROAM_* 互补齐。幂等，进程启动时调一次。
func BridgeEnvAliases() {
	for _, kv := range os.Environ() {
		key, val, ok := strings.Cut(kv, "=")
		if !ok || val == "" {
			continue
		}
		switch {
		case strings.HasPrefix(key, newEnvPrefix):
			if old := oldEnvPrefix + strings.TrimPrefix(key, newEnvPrefix); os.Getenv(old) == "" {
				_ = os.Setenv(old, val)
			}
		case strings.HasPrefix(key, oldEnvPrefix):
			if nw := newEnvPrefix + strings.TrimPrefix(key, oldEnvPrefix); os.Getenv(nw) == "" {
				_ = os.Setenv(nw, val)
			}
		}
	}
}
