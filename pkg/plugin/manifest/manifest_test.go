package manifest

import "testing"

func sample() Manifest {
	return Manifest{
		ManifestVersion: 1,
		ID:              "acme.qc",
		Publisher:       "acme",
		Name:            "qc",
		Version:         "0.1.0",
		Runtime:         Runtime{Kind: "builtin"},
		Permissions: Perms{
			Workspace: []string{"read"},
			Commands:  CommandPerms{Allow: []string{"scripts/dev/quality/check.sh", "go test"}, Deny: []string{"go test -run TestDanger"}},
		},
		Contributes: Contribs{
			Commands:          []CommandContrib{{ID: "qc.review"}},
			NotificationSinks: []SinkContrib{{ID: "qc.sink", Events: []string{"finding.blocking"}}},
		},
	}
}

func TestValidateOK(t *testing.T) {
	if err := sample().Validate(); err != nil {
		t.Fatal(err)
	}
}

func TestValidateRejects(t *testing.T) {
	m := sample()
	m.ID = "noPublisher"
	if err := m.Validate(); err == nil {
		t.Fatal("id without publisher accepted")
	}
	m = sample()
	m.Contributes.Commands = []CommandContrib{{ID: "other.review"}}
	if err := m.Validate(); err == nil {
		t.Fatal("foreign command prefix accepted")
	}
	m = sample()
	m.Runtime.Kind = "node" // main missing
	if err := m.Validate(); err == nil {
		t.Fatal("node runtime without main accepted")
	}
	m = sample()
	m.Contributes.Commands = []CommandContrib{{ID: "qc.re:view"}} // 冒号是 id 限定形式的保留分隔符
	if err := m.Validate(); err == nil {
		t.Fatal("command id with ':' accepted")
	}
	m = sample()
	m.ID = "ac:me.qc" // 同上:id 含冒号会让 <id>:<handler> 解析永远失败
	if err := m.Validate(); err == nil {
		t.Fatal("plugin id with ':' accepted")
	}
}

func TestCommandOwner(t *testing.T) {
	m := sample()
	handler, ok := m.CommandOwner("qc.review")
	if !ok || handler != "review" {
		t.Fatalf("want review/true, got %q/%v", handler, ok)
	}
	if _, ok := m.CommandOwner("qc.unknown"); ok {
		t.Fatal("undeclared command accepted")
	}
	if _, ok := m.CommandOwner("other.review"); ok {
		t.Fatal("foreign command accepted")
	}
}

func TestFullCommandOwner(t *testing.T) {
	m := sample()
	handler, ok := m.FullCommandOwner("acme.qc:review")
	if !ok || handler != "review" {
		t.Fatalf("want review/true, got %q/%v", handler, ok)
	}
	if _, ok := m.FullCommandOwner("qc.review"); ok {
		t.Fatal("short form must not match the id-qualified resolver")
	}
	if _, ok := m.FullCommandOwner("evil.qc:review"); ok {
		t.Fatal("forged id accepted")
	}
	if _, ok := m.FullCommandOwner("acme.qc:unknown"); ok {
		t.Fatal("undeclared command accepted")
	}
}

func TestCommandAllowed(t *testing.T) {
	m := sample()
	if !m.CommandAllowed([]string{"go", "test", "./..."}) {
		t.Fatal("whitelisted prefix rejected")
	}
	if m.CommandAllowed([]string{"rm", "-rf", "/"}) {
		t.Fatal("non-whitelisted command accepted")
	}
	if m.CommandAllowed([]string{"go", "test", "-run", "TestDanger"}) {
		t.Fatal("deny rule ignored")
	}
}

func TestSinkMatches(t *testing.T) {
	m := sample()
	if !m.SinkMatches("finding.blocking") || m.SinkMatches("other.type") {
		t.Fatal("sink matching wrong")
	}
	m.Contributes.NotificationSinks[0].Events = []string{"*"}
	if !m.SinkMatches("anything") {
		t.Fatal("wildcard sink not matching")
	}
}

func TestHasPerm(t *testing.T) {
	m := sample()
	if !m.HasPerm("workspace:read") {
		t.Fatal("declared perm rejected")
	}
	if m.HasPerm("workspace:write") || m.HasPerm("agents:spawn") {
		t.Fatal("undeclared perm accepted")
	}
}

// ── 状态条贡献点(docs/design/web/20-status-bar §05)──────────────────────

func f64(v float64) *float64 { return &v }

func withStatus(items ...StatusItem) Manifest {
	m := sample()
	m.Contributes.StatusItems = items
	return m
}

func okItem() StatusItem {
	return StatusItem{
		ID: "cpu", Align: "left", Render: "gauge", Tier: 2,
		Source: StatusSrc{Command: "qc.review", Refresh: 3, Path: "cpu.usagePercent"},
		Thresh: &StatusThr{Warn: f64(70), Danger: f64(95), SustainSec: 60},
		Click:  &StatusAct{Kind: "pluginView", ID: "acme.qc"},
	}
}

func TestStatusItemAccepted(t *testing.T) {
	if err := withStatus(okItem()).Validate(); err != nil {
		t.Fatalf("valid status item rejected: %v", err)
	}
}

func TestStatusItemRejects(t *testing.T) {
	bad := func(name string, mutate func(*StatusItem)) {
		t.Helper()
		it := okItem()
		mutate(&it)
		if err := withStatus(it).Validate(); err == nil {
			t.Fatalf("%s should be rejected", name)
		}
	}
	bad("empty id", func(i *StatusItem) { i.ID = "" })
	// 全局 id 是 <插件id>/<id>,所以 '/' 必须留给分隔符
	bad("id with slash", func(i *StatusItem) { i.ID = "a/b" })
	bad("unknown align", func(i *StatusItem) { i.Align = "center" })
	bad("unknown render", func(i *StatusItem) { i.Render = "canvas" })
	bad("tier out of range", func(i *StatusItem) { i.Tier = 9 })
	bad("unknown click kind", func(i *StatusItem) { i.Click = &StatusAct{Kind: "eval"} })
	// 命令必须是本插件声明过的:否则宿主会去调一个不存在的 handler,每 3 秒一次
	bad("undeclared command", func(i *StatusItem) { i.Source.Command = "qc.nope" })
	bad("no path", func(i *StatusItem) { i.Source.Path = ""; i.Source.TextPath = "" })
	// plugin run 每次起一个子进程,2s 是地板
	bad("refresh below floor", func(i *StatusItem) { i.Source.Refresh = 1 })
}

func TestStatusItemDuplicateID(t *testing.T) {
	if err := withStatus(okItem(), okItem()).Validate(); err == nil {
		t.Fatal("duplicate status item id accepted")
	}
}

func TestStatusItemBudget(t *testing.T) {
	seven := make([]StatusItem, 0, 7)
	for i := 0; i < 7; i++ {
		it := okItem()
		it.ID = string(rune('a' + i))
		seven = append(seven, it)
	}
	// builtin 上限 6
	if err := withStatus(seven...).Validate(); err == nil {
		t.Fatal("7 items on a builtin plugin accepted")
	}
	if err := withStatus(seven[:6]...).Validate(); err != nil {
		t.Fatalf("6 items on a builtin plugin rejected: %v", err)
	}
	// 第三方上限 2:一条 24px 的槽装不下三个插件各五格
	third := withStatus(seven[:3]...)
	third.Runtime = Runtime{Kind: "exec"}
	third.Main = "main.sh"
	if err := third.Validate(); err == nil {
		t.Fatal("3 items on a third-party plugin accepted")
	}
	third.Contributes.StatusItems = seven[:2]
	if err := third.Validate(); err != nil {
		t.Fatalf("2 items on a third-party plugin rejected: %v", err)
	}
}

func TestPushItemNeedsNoCommand(t *testing.T) {
	it := okItem()
	it.Source = StatusSrc{Push: true}
	if err := withStatus(it).Validate(); err != nil {
		t.Fatalf("push item rejected: %v", err)
	}
}
