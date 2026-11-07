package memrelief

import (
	"testing"
	"time"
)

func TestRecoveryIsBoundedAndDoesNotTouchPausedOrResumedWork(t *testing.T) {
	now := time.Unix(2000, 0)
	s := []Sample{{Name: "small", Current: 650 << 20, Limit: 1 << 30}, {Name: "large", Current: 2 << 30, Limit: 3 << 30}}
	if Target(s, false, now) != "large" {
		t.Fatal("largest warning must recover first")
	}
	s[1].State.ReclaimAt = now.Unix()
	if Target(s, false, now) != "small" {
		t.Fatal("cooldown must survive observations")
	}
	s[0].Paused = true
	s[1].Grace = true
	if Target(s, true, now) != "" {
		t.Fatal("paused and grace work must stay untouched")
	}
	if n := Bytes(8<<30, 64<<20); n != 32<<20 {
		t.Fatalf("swap budget exceeded: %d", n)
	}
	if Bytes(1<<30, 8<<20) != 0 {
		t.Fatal("insufficient swap must not trigger reclaim")
	}
}

func TestCompactionRefusesBusyDraftsShellsAndDialogs(t *testing.T) {
	for _, tc := range []struct {
		kind, screen string
		row          int
		want         bool
	}{
		{"codex", "answer\n› \nfooter", 1, true}, {"claude", "answer\n❯ \nfooter", 1, true},
		{"codex", "answer\n›\n\nfooter", 2, true},
		{"codex", "› draft\n\nfooter", 1, false},
		{"codex", "›\nfirst draft line\n\nfooter", 2, false},
		{"codex", "› user draft\nfooter", 0, false}, {"claude", "❯ \nesc to interrupt", 0, false},
		{"bash", "› \n", 0, false}, {"codex", "› \nApprove this command", 0, false},
		{"codex", "› \n", 5, false}, {"claude", "❯ \n", -1, false},
	} {
		if got := EmptyPrompt(tc.kind, tc.screen, tc.row); got != tc.want {
			t.Fatalf("%+v: got %v", tc, got)
		}
	}
}
