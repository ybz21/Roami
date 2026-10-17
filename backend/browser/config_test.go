package browser

import "testing"

// 模式值的收敛表。chrome CLI（backend/browser/automation/launcher.sh 的 _load_browser_cfg）照抄了这张表，
// 改这里要一起改那边，否则 CLI 和后端会对同一份配置得出不同的无头/有头结论。
func TestNormalizeHeadless(t *testing.T) {
	cases := map[string]string{
		"auto": "auto", "on": "on", "off": "off",
		"AUTO": "auto", " off ": "off",
		"new": "on", "true": "on", "1": "on", // 手改/历史野值
		"false": "off", "0": "off",
		"":   "", // 未设 → 交给 pick 回落
		"乱写": "",
	}
	for in, want := range cases {
		if got := normalizeHeadless(in); got != want {
			t.Errorf("normalizeHeadless(%q) = %q, want %q", in, got, want)
		}
	}
}

// 「存的值 > 环境变量 > 默认」这条链 chrome CLI 也照抄了一份（_load_browser_cfg），
// 两边任一侧改了优先级，同一台机器上两个 launcher 就会起出参数不同的 Chrome。
func TestEffectiveConfigFallsBackToEnv(t *testing.T) {
	dir := t.TempDir()
	InitConfig(dir)
	t.Cleanup(func() {
		cfgStore.mu.Lock()
		cfgStore.file, cfgStore.portFile = "", ""
		cfgStore.mu.Unlock()
	})
	t.Setenv("TTMUX_CHROME_WINDOW", "800,600")
	t.Setenv("TTMUX_CHROME_SCALE", "1.25")
	t.Setenv("TTMUX_CHROME_PROFILE", "/tmp/env-profile")
	t.Setenv("TTMUX_CHROME_FULLSCREEN", "0")

	if err := saveConfig(Config{Scale: "3"}); err != nil { // 只存了 scale：其余走 env
		t.Fatal(err)
	}
	got := effectiveConfig()
	if got.WindowSize != "800,600" || got.Profile != "/tmp/env-profile" {
		t.Errorf("env 回落失败: window=%q profile=%q", got.WindowSize, got.Profile)
	}
	if got.Scale != "3" { // 存了就赢过 env
		t.Errorf("Scale = %q, want 3", got.Scale)
	}
	if got.Fullscreen == nil || *got.Fullscreen {
		t.Error("TTMUX_CHROME_FULLSCREEN=0 应关掉全屏")
	}
}

// 无法识别的模式必须回显成 auto：分段控件选不中任何一项时，用户看到的是「没选」，
// 而后端仍会按某个模式跑——界面和实际就此对不上。
func TestEffectiveConfigHeadlessFallsBackToAuto(t *testing.T) {
	dir := t.TempDir()
	InitConfig(dir)
	t.Cleanup(func() {
		cfgStore.mu.Lock()
		cfgStore.file, cfgStore.portFile = "", ""
		cfgStore.mu.Unlock()
	})

	if err := saveConfig(Config{Headless: "乱写"}); err != nil {
		t.Fatal(err)
	}
	if got := effectiveConfig().Headless; got != "auto" {
		t.Errorf("Headless = %q, want auto", got)
	}
	if err := saveConfig(Config{Headless: "new"}); err != nil {
		t.Fatal(err)
	}
	if got := effectiveConfig().Headless; got != "on" {
		t.Errorf("Headless = %q, want on", got)
	}
}
