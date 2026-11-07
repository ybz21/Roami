package config

import (
	"os"
	"testing"
)

// 改名不能让老脚本失灵：ROAM_* 与 ROAMI_* 必须互相看得见。
func TestBridgeEnvAliases(t *testing.T) {
	t.Setenv("ROAM_WEB_PASSWORD", "老脚本写的")
	t.Setenv("ROAMI_WEB_PASSWORD", "")
	t.Setenv("ROAMI_HOME", "/tmp/new")
	t.Setenv("ROAM_HOME", "")
	t.Setenv("ROAM_DATA", "/tmp/old-data")
	t.Setenv("ROAMI_DATA", "/tmp/new-data") // 两个都写：新名说了算
	BridgeEnvAliases()

	if got := os.Getenv("ROAMI_WEB_PASSWORD"); got != "老脚本写的" {
		t.Errorf("老名字该被新名字看见，got %q", got)
	}
	if got := os.Getenv("ROAM_HOME"); got != "/tmp/new" {
		t.Errorf("新名字该被老读取点看见，got %q", got)
	}
	if got := os.Getenv("ROAMI_DATA"); got != "/tmp/new-data" {
		t.Errorf("两个都写时以新名为准，got %q", got)
	}
	if got := os.Getenv("ROAM_DATA"); got != "/tmp/old-data" {
		t.Errorf("已有的老值不该被覆盖，got %q", got)
	}
}
