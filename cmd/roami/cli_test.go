package main

import (
	"reflect"
	"strings"
	"testing"
)

func demoPlugins() []pluginInfo {
	return []pluginInfo{
		{ID: "roam.cron", Name: "cron", Enabled: true},
		{ID: "roam.im-bridge", Name: "im-bridge", Enabled: true},
		{ID: "roam.host-monitor", Name: "host-monitor", Enabled: true},
		{ID: "roam.review-mesh", Name: "review-mesh", Enabled: true},
	}
}

// 名字按唯一前缀认：谁也不想为了发条消息去背「im-bridge」这个全名。
func TestResolveGroup(t *testing.T) {
	ps := demoPlugins()
	for word, want := range map[string]string{
		"cron":           "roam.cron",
		"im":             "roam.im-bridge",
		"im-bridge":      "roam.im-bridge",
		"roam.im-bridge": "roam.im-bridge",
		"host":           "roam.host-monitor",
		"rev":            "roam.review-mesh",
	} {
		got, err := resolveGroup(ps, word)
		if err != nil || got == nil {
			t.Errorf("%q 没认出来：%v", word, err)
			continue
		}
		if got.ID != want {
			t.Errorf("%q → %s，想要 %s", word, got.ID, want)
		}
	}

	// 认不出不是错：调用方会把它转发给 ttmux（roam ls / roam swarm … 照用）
	if got, err := resolveGroup(ps, "ls"); got != nil || err != nil {
		t.Errorf("ls 不该被当成插件组：%v %v", got, err)
	}
}

// 前缀撞了必须报错。猜一个跑出去比说不认识危险得多。
func TestResolveGroupAmbiguous(t *testing.T) {
	ps := append(demoPlugins(), pluginInfo{ID: "acme.reporter", Name: "reporter", Enabled: true})
	got, err := resolveGroup(ps, "re")
	if got != nil || err == nil {
		t.Fatalf("撞名该报错，got %v err %v", got, err)
	}
	for _, want := range []string{"reporter", "review-mesh"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("错误里该列出 %q：%s", want, err)
		}
	}
}

// 转发给 ttmux 的是 id 限定形式：短名撞名时归属才不会落到别人家
func TestPluginRunArgs(t *testing.T) {
	got := pluginRunArgs(pluginInfo{ID: "roam.im-bridge", Name: "im-bridge"}, "send", []string{"--text", "跑完了"})
	want := []string{"plugin", "run", "roam.im-bridge:send", "--text", "跑完了"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
}

func TestShortCmd(t *testing.T) {
	if got := shortCmd("cron.list"); got != "list" {
		t.Errorf("shortCmd = %q", got)
	}
	if got := shortCmd("list"); got != "list" {
		t.Errorf("没有前缀时该原样返回，got %q", got)
	}
}

// 子命令层不能吃掉「启动服务」这条老路：第一个参数是 flag 时必须放行
func TestRunCLILeavesFlagsAlone(t *testing.T) {
	for _, args := range [][]string{{}, {"-addr", ":13579"}, {"--tls"}} {
		if handled, _ := runCLI(args, "ttmux"); handled {
			t.Errorf("%v 不该被子命令层接管", args)
		}
	}
}
