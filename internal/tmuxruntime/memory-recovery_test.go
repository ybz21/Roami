package runtime

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/memrelief"
)

func TestRecoveryStateSurvivesFreshCLICalls(t *testing.T) {
	r := fakeTmux(t, sampleRows)
	r.Now = func() time.Time { return time.Unix(4000, 0) }
	state := memrelief.State{ReclaimAt: 4000, ReclaimStatus: "done", Reclaimed: 32 << 20, CompactAt: 3900, CompactStatus: "requested"}
	if err := r.saveMemoryRelief("one", state); err != nil {
		t.Fatal(err)
	}
	next := r
	next.DataDir = filepath.Clean(r.DataDir)
	if got := next.MemoryReliefState("one"); got != state {
		t.Fatalf("state lost: %+v", got)
	}
	if err := os.WriteFile(r.memoryStatePath("one"), []byte("broken"), 0600); err != nil {
		t.Fatal(err)
	}
	if got := next.MemoryReliefState("one"); got.ReclaimStatus != "" {
		t.Fatal("invalid state reported success")
	}
}

func TestCompactNeverSendsToAShellOrUnknownPane(t *testing.T) {
	r := fakeTmux(t, sampleRows)
	r.Now = time.Now
	state, err := r.CompactSession("我的会话", false)
	if err == nil || state.CompactStatus != "unsupported" {
		t.Fatalf("unknown pane accepted: %+v %v", state, err)
	}
	if state.CompactAt != 0 {
		t.Fatal("rejected compaction marked as delivered")
	}
}

func TestCompactionRecognizesOnlyInteractiveLaunchArguments(t *testing.T) {
	for _, tc := range []struct {
		argv []string
		want string
	}{
		{[]string{"node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js", "prompt mentions codex"}, "claude"},
		{[]string{"codex", "prompt mentions claude"}, "codex"},
		{[]string{"codex", "app-server"}, ""}, {[]string{"codex", "exec", "do work"}, ""},
		{[]string{"bash", "-lc", "codex"}, ""}, {[]string{"claude", "-p", "prompt"}, ""},
	} {
		if got := compactLaunchKind(tc.argv); got != tc.want {
			t.Fatalf("%q: %q", tc.argv, got)
		}
	}
}
