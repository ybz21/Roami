package api

import (
	"testing"
	"time"
)

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

func TestProjectRunningUsesSameLiveStateAsOverview(t *testing.T) {
	a := &API{}
	a.Live.set("opencode-pane", liveSnap{Agent: "opencode", Busy: true, At: time.Now()})
	if !a.sessionRunning("opencode-pane", "opencode", "New session", false) {
		t.Fatal("active OpenCode service session must count while TUI shows New session")
	}
	if a.sessionRunning("opencode-pane", "opencode", "New session", true) {
		t.Fatal("waiting session must not also count as running")
	}
}
