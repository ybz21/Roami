package id

import "testing"

// 格式断言：与 CLI 侧 cli/github.com/ybz21/Roami/internal/id 同款，两边都有这条，防止格式漂。
func TestNewMatchesFormat(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 50; i++ {
		v := New()
		if !Valid(v) {
			t.Fatalf("id %q 不符合 YYYY-MMDD-HHMM-rand4", v)
		}
		seen[v] = true
	}
	if len(seen) < 40 { // 同分钟内靠 rand4 区分，撞几个正常，成片相同就是随机源坏了
		t.Fatalf("50 次只生成 %d 个不同 id", len(seen))
	}
}

func TestValidRejectsLegacyKeys(t *testing.T) {
	for _, s := range []string{"", "ttmux-3f2a", "race-1753670000000000000", "2026-0728-1113-ASBD", "2026-0728-1113"} {
		if Valid(s) {
			t.Fatalf("不该认作 id: %q", s)
		}
	}
}
