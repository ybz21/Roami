package api

import "testing"

func TestLiveSessionRunningMatchesAgentPresence(t *testing.T) {
	for _, kind := range []string{"claude", "codex", "pi", "opencode"} {
		if (liveSnap{Agent: kind, Busy: false}).running() {
			t.Fatalf("%s process at prompt must not count as running", kind)
		}
		if !(liveSnap{Agent: kind, Busy: true}).running() {
			t.Fatalf("%s responding must count as running", kind)
		}
		if (liveSnap{Agent: kind, Busy: true, Waiting: true}).running() {
			t.Fatalf("%s waiting for input must be counted separately", kind)
		}
	}
	if (liveSnap{Busy: true}).running() {
		t.Fatal("session without an agent process cannot count as running")
	}
}
