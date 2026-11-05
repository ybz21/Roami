package api

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/ybz21/Roami/backend/ttmux"
	"github.com/ybz21/Roami/backend/worktree"
)

func TestOverviewRetainsAncestryActivityAndDirectoryWithoutWorktree(t *testing.T) {
	a, router, _ := projectOKRFixture(t)
	bin := filepath.Join(t.TempDir(), "overview-cli")
	script := "#!/bin/sh\n[ \"$*\" = 'ls --json' ] || exit 1\ncat <<'JSON'\n" +
		`[{"name":"child","label":"Review","parent":"parent","last_activity":200,"dir":"/notes","state":"dormant"},{"name":"parent","last_activity":100}]` + "\nJSON\n"
	if err := os.WriteFile(bin, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("TMUX_BIN", bin)
	t.Setenv("TMUX", "")
	a.TT = ttmux.New(bin)
	a.WT = worktree.New(t.TempDir(), a.Meta)
	router.GET("/sessions/overview", a.SessionsOverview)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest("GET", "/sessions/overview", nil))
	var result struct {
		Data struct {
			Items []overviewItem `json:"items"`
		} `json:"data"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if response.Code != 200 || len(result.Data.Items) != 2 {
		t.Fatalf("overview: %d %s", response.Code, response.Body)
	}
	child := result.Data.Items[0]
	if child.Parent != "parent" || child.LastActivity != 200 || child.Cwd != "/notes" || child.Worktree != "" {
		t.Fatalf("lost independent session fields: %+v", child)
	}
}

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
