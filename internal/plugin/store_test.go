package plugin

import (
	"path/filepath"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func testStore(t *testing.T) *Store {
	t.Helper()
	tmp := t.TempDir()
	rt := runtime.Runtime{
		HomeDir: filepath.Join(tmp, "home"),
		DataDir: filepath.Join(tmp, "data"),
		Now:     time.Now,
	}
	s, err := Open(NewEnv(rt))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}

// FindCommand 的归属解析:id 限定形式(<id>:<cmd>)只按全 id 精确匹配,
// 不回退短名——否则短名恰好撞上限定串的插件(如短名 evil 声明
// evil.host-monitor.stats)会接走伪造 id(evil.host-monitor)的调用。
func TestFindCommandQualifiedNoFallback(t *testing.T) {
	s := testStore(t)
	victim := Manifest{
		ManifestVersion: 1, ID: "roam.host-monitor", Publisher: "roam", Name: "host-monitor",
		Version: "0.1.0", Runtime: Runtime{Kind: "builtin"},
		Contributes: Contribs{Commands: []CommandContrib{{ID: "host-monitor.stats"}}},
	}
	evil := Manifest{
		ManifestVersion: 1, ID: "x.evil", Publisher: "x", Name: "evil",
		Version: "0.1.0", Runtime: Runtime{Kind: "builtin"},
		Contributes: Contribs{Commands: []CommandContrib{{ID: "evil.host-monitor.stats"}}},
	}
	for _, m := range []Manifest{victim, evil} {
		if err := m.Validate(); err != nil {
			t.Fatal(err)
		}
		if err := s.SyncBuiltin(m); err != nil {
			t.Fatal(err)
		}
	}

	// 短名与 id 限定两种形式都解析到正主
	if p, h, err := s.FindCommand("host-monitor.stats"); err != nil || p.Manifest.ID != victim.ID || h != "stats" {
		t.Fatalf("short form: got %v/%q/%v", p.Manifest.ID, h, err)
	}
	if p, h, err := s.FindCommand("roam.host-monitor:stats"); err != nil || p.Manifest.ID != victim.ID || h != "stats" {
		t.Fatalf("qualified form: got %v/%q/%v", p.Manifest.ID, h, err)
	}
	// 伪造 id 的限定串查无此插件即拒,不得被 x.evil 的短名命令接走
	if p, _, err := s.FindCommand("evil.host-monitor:stats"); err == nil {
		t.Fatalf("forged qualified id resolved to %s", p.Manifest.ID)
	}
	// evil 自己的短名命令仍归 evil(合法行为,不受限定解析影响)
	if p, _, err := s.FindCommand("evil.host-monitor.stats"); err != nil || p.Manifest.ID != evil.ID {
		t.Fatalf("evil's own command: got %v/%v", p.Manifest.ID, err)
	}
}
