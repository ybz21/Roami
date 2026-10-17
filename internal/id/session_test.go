package id

import (
	"regexp"
	"testing"
	"time"
)

// 格式断言：与后端 backend/internal/id 同款，两边都有这条，防止格式漂。
func TestNewAtMatchesFormat(t *testing.T) {
	at := time.Date(2026, 7, 28, 11, 13, 0, 0, time.UTC)
	v := NewAt(at)
	if !Valid(v) {
		t.Fatalf("id %q 不符合 YYYY-MMDD-HHMM-rand4", v)
	}
	if v[:15] != "2026-0728-1113-" {
		t.Fatalf("id 前缀应是创建时刻，got %q", v)
	}
}

func TestValidRejectsOthers(t *testing.T) {
	for _, s := range []string{"", "swarm1", "2026-0728-1113", "2026-0728-1113-ASBD"} {
		if Valid(s) {
			t.Fatalf("不该认作 id: %q", s)
		}
	}
}

// 会话 id 展示格式：由 tmux 的 created + $142 派生，和项目/蜂群同款可读格式，
// 且与 session_id 一一对应（同一会话永远算出同一个）。
func TestForSession(t *testing.T) {
	at := time.Date(2026, 7, 28, 11, 50, 0, 0, time.Local).Unix()
	got := ForSession(at, "$142")
	if got != "2026-0728-1150-003y" {
		t.Fatalf("ForSession = %q", got)
	}
	if !Valid(got) {
		t.Fatalf("派生 id 应符合统一格式: %q", got)
	}
	if again := ForSession(at, "$142"); again != got {
		t.Fatal("同一会话必须稳定算出同一个 id")
	}
	if same := ForSession(at, "$143"); same == got {
		t.Fatal("同分钟不同会话必须不同")
	}
	// 大号会话也还是 4 位（base36 到 167 万）
	if v := ForSession(at, "$1679615"); !Valid(v) {
		t.Fatalf("大 id 溢出格式: %q", v)
	}
	// 数据不全 → 原样给 tmux id，不编造
	if v := ForSession(0, "$142"); v != "$142" {
		t.Fatalf("缺 created 应回落原始 id, got %q", v)
	}
	if v := ForSession(at, ""); v != "" {
		t.Fatalf("缺 tmux id 应回落空串, got %q", v)
	}
}

// UUID 必须是合法 v4 —— Claude Code 的 --session-id 只认合法 UUID，
// 格式不对会话就起不来，而这条链路是「重开并接回原对话」的地基。
func TestUUIDIsValidV4(t *testing.T) {
	re := regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
	seen := map[string]bool{}
	for i := 0; i < 200; i++ {
		u := UUID()
		if !re.MatchString(u) {
			t.Fatalf("不是合法 v4 UUID: %q", u)
		}
		if seen[u] {
			t.Fatalf("重复: %q", u)
		}
		seen[u] = true
	}
}
