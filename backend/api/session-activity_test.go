package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/ttmux"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestSessionActivitySkipsQuietBackgroundAndKeepsKnownValueOnFailedCapture(t *testing.T) {
	row := sessListItem{Name: "task", TmuxID: "$1", Created: "100"}
	panes := []sessionPane{{id: "%1", activity: 110}, {id: "%2", activity: 115}}
	screens := map[string]string{"%1": "  ready\n", "%2": "background"}
	var captured []string
	capture := func(id string) (string, bool) {
		captured = append(captured, id)
		screen, ok := screens[id]
		return screen, ok
	}
	activity := (sessionActivity{}).observe(row, panes, 120, capture)
	if activity.at != 115 {
		t.Fatalf("initial activity = %d, want 115", activity.at)
	}
	captured = nil
	panes[0].activity = 120
	screens["%1"] = "\nready      \n\n"
	activity = activity.observe(row, panes, 130, capture)
	if activity.at != 115 || strings.Join(captured, ",") != "%1" {
		t.Fatalf("same-second redraw: activity = %d, captured %v", activity.at, captured)
	}
	panes[0].activity = 140
	delete(screens, "%1")
	activity = activity.observe(row, panes, 141, capture)
	if activity.at != 115 {
		t.Fatalf("failed capture changed activity to %d", activity.at)
	}
	screens["%1"] = "new response"
	activity = activity.observe(row, panes, 142, capture)
	if activity.at != 140 {
		t.Fatalf("capture after recovery: activity = %d, want 140", activity.at)
	}
	row.Created = "200"
	panes = []sessionPane{{id: "%1", activity: 210}}
	activity = activity.observe(row, panes, 220, capture)
	if activity.identity != "$1:200" || activity.at != 210 {
		t.Fatalf("recreated session reused prior observation: %+v", activity)
	}
}

func TestSessionActivityIgnoresAgentChromeAndKeepsShellOutput(t *testing.T) {
	before := "The response is ready.\n✻ Working for 1s\n⠋ Working"
	after := "The response is ready.\n✻ Working for 2s\n⠙ Working"
	if paneActivityHash(before, true) != paneActivityHash(after, true) {
		t.Fatal("changing Agent chrome changed the activity fingerprint")
	}
	if paneActivityHash(before, false) == paneActivityHash(after, false) {
		t.Fatal("shell output resembling Agent chrome was ignored")
	}
	if paneActivityHash(before, true) == paneActivityHash("A new response.\n✻ Working for 2s", true) {
		t.Fatal("new response did not change the activity fingerprint")
	}
}

func TestSessionActivityProjectionPreservesTreeFields(t *testing.T) {
	var live liveTable
	live.set("child", liveSnap{Activity: sessionActivity{identity: "$2:100", at: 125}})
	const body = `[{"name":"parent","last_activity":99,"children":[
		{"name":"child","tmux_id":"$2","created":"100","last_activity":"200","mem":{"paused":true}},
		{"name":"child","tmux_id":"$2","created":"101","last_activity":210},
		{"name":"child","tmux_id":"$2","created":"100","last_activity":220,"state":"dormant"}
	]}]`
	var rows []struct {
		LastActivity int `json:"last_activity"`
		Children     []map[string]json.RawMessage
	}
	if err := json.Unmarshal(live.projectSessionActivity([]byte(body)), &rows); err != nil {
		t.Fatal(err)
	}
	children := rows[0].Children
	if len(children) != 3 || string(children[0]["last_activity"]) != `"125"` ||
		string(children[0]["mem"]) != `{"paused":true}` ||
		string(children[1]["last_activity"]) != "210" || string(children[2]["last_activity"]) != "220" {
		t.Fatalf("wrong projected tree: %s", live.projectSessionActivity([]byte(body)))
	}
}

const activityFixture = "ROAMI_ACTIVITY_TEST_CHILD"

func TestSessionActivityIsolatedE2E(t *testing.T) {
	if os.Getenv(activityFixture) != "1" {
		if _, err := exec.LookPath("tmux"); err != nil {
			t.Skip("tmux is unavailable")
		}
		launcher, err := filepath.Abs("../../scripts/dev/isolated-roami.sh")
		if err != nil {
			t.Fatal(err)
		}
		instance := t.TempDir()
		t.Cleanup(func() {
			if out, err := exec.Command(launcher, instance, "--stop").CombinedOutput(); err != nil {
				t.Errorf("stop isolated instance: %v: %s", err, out)
			}
		})
		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, launcher, instance, "env", activityFixture+"=1", os.Args[0], "-test.run=^TestSessionActivityIsolatedE2E$", "-test.v")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("isolated session activity: %v\n%s", err, out)
		}
		t.Logf("isolated tmux:\n%s", out)
		return
	}

	rt := runtime.New()
	tt := ttmux.New("roami")
	a := New(tt, "", rt.DataDir, "")
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.GET("/sessions", a.Sessions)
	router.GET("/sessions/overview", a.SessionsOverview)
	router.GET("/projects", a.ProjectsList)

	tmux := func(args ...string) {
		t.Helper()
		if out, err := exec.Command(rt.TmuxBin, args...).CombinedOutput(); err != nil {
			t.Fatalf("tmux %v: %v: %s", args, err, out)
		}
	}

	const name = "activity-check"
	const terminal = "stty -echo; printf 'ready'; while IFS= read -r line; do printf '\\r\\033[2K%s' \"$line\"; done"
	agent := filepath.Join(t.TempDir(), "codex")
	agentScript := `#!/bin/sh
stty -echo
printf 'ready\n✻ Working for 1s'
while IFS= read -r line; do
  printf '\r\033[2K%s' "$line"
done
`
	if err := os.WriteFile(agent, []byte(agentScript), 0700); err != nil {
		t.Fatal(err)
	}
	tmux("new-session", "-d", "-s", name, "-n", "foreground", agent)
	tmux("new-window", "-d", "-t", "="+name+":", "-n", "background", terminal)

	sessionRow := func() sessListItem {
		t.Helper()
		out, err := tt.Run("ls", "--json")
		if err != nil {
			t.Fatal(err)
		}
		var rows []sessListItem
		if err := json.Unmarshal([]byte(out), &rows); err != nil {
			t.Fatal(err)
		}
		for _, row := range rows {
			if row.Name == name {
				return row
			}
		}
		t.Fatal("session omitted from CLI list")
		return sessListItem{}
	}

	waitForSample := func(after time.Time) liveSnap {
		t.Helper()
		deadline := time.Now().Add(8 * time.Second)
		for time.Now().Before(deadline) {
			if snap, ok := a.Live.get(name); ok && snap.At.After(after) {
				return snap
			}
			time.Sleep(25 * time.Millisecond)
		}
		t.Fatal("session probe did not publish a sample")
		return liveSnap{}
	}

	get := func(path string, into any) {
		t.Helper()
		rec := httptest.NewRecorder()
		router.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
		if rec.Code != http.StatusOK {
			t.Fatalf("%s: HTTP %d: %s", path, rec.Code, rec.Body.String())
		}
		if err := json.Unmarshal(rec.Body.Bytes(), into); err != nil {
			t.Fatalf("%s: %v", path, err)
		}
	}

	checkHTTP := func(want int64) {
		t.Helper()
		var flat, tree []sessListItem
		var overview struct {
			Data struct{ Items []overviewItem }
		}
		var projects struct {
			Data struct {
				Loose    []projectSession
				Projects []projectSummary
			}
		}
		get("/sessions", &flat)
		get("/sessions?tree=1", &tree)
		get("/sessions/overview", &overview)
		for _, rows := range [][]sessListItem{flat, tree} {
			found := false
			for _, row := range rows {
				if row.Name == name {
					found = true
					if rawInt(row.LastActivity) != want {
						t.Fatalf("session list activity = %s, want %d", row.LastActivity, want)
					}
				}
			}
			if !found {
				t.Fatal("session omitted from a session list")
			}
		}
		gotOverview := int64(0)
		for _, row := range overview.Data.Items {
			if row.Name == name {
				gotOverview = row.LastActivity
			}
		}
		if gotOverview != want {
			t.Fatalf("overview activity = %d, want %d", gotOverview, want)
		}
		// Projects can serve the previous sample from their five-second cache.
		deadline := time.Now().Add(6 * time.Second)
		for {
			get("/projects", &projects)
			top := projects.Data.Loose
			for _, project := range projects.Data.Projects {
				top = append(top, project.Top...)
			}
			for _, row := range top {
				if row.Name == name && row.LastActivity == want {
					return
				}
			}
			if time.Now().After(deadline) {
				t.Fatalf("project did not report activity %d: %+v", want, top)
			}
			time.Sleep(100 * time.Millisecond)
		}
	}

	send := func(window, line string) {
		t.Helper()
		target := "=" + name + ":" + window
		tmux("send-keys", "-t", target, "-l", line)
		tmux("send-keys", "-t", target, "Enter")
	}

	go a.SessionEventLoop()
	first := waitForSample(time.Time{})
	before := rawInt(sessionRow().LastActivity)
	if first.Activity.at != before || before == 0 {
		t.Fatalf("initial activity = %d, raw %d", first.Activity.at, before)
	}
	t.Logf("Initial                        tmux=%d  observed=%d", before, first.Activity.at)

	send("background", "ready")
	redraw := waitForSample(time.Now())
	rawRedraw := rawInt(sessionRow().LastActivity)
	if rawRedraw <= before || redraw.Activity.at != before {
		t.Fatalf("identical redraw: raw = %d, confirmed = %d, started at %d", rawRedraw, redraw.Activity.at, before)
	}
	t.Logf("Redrew the same text           tmux=%d  observed=%d", rawRedraw, redraw.Activity.at)

	send("foreground", "✻ Working for 2s")
	updatedChrome := waitForSample(time.Now())
	rawChrome := rawInt(sessionRow().LastActivity)
	if rawChrome <= rawRedraw || updatedChrome.Agent != "codex" || updatedChrome.Activity.at != before {
		t.Fatalf("Agent timer: raw = %d, observed = %d, agent = %q, started at %d", rawChrome, updatedChrome.Activity.at, updatedChrome.Agent, before)
	}
	t.Logf("Agent chrome timer incremented tmux=%d  observed=%d", rawChrome, updatedChrome.Activity.at)

	tmux("select-window", "-t", "="+name+":background")
	switched := waitForSample(time.Now())
	rawSwitch := rawInt(sessionRow().LastActivity)
	if rawSwitch <= rawChrome || switched.Activity.at != before {
		t.Fatalf("window switch: raw = %d, confirmed = %d, started at %d", rawSwitch, switched.Activity.at, before)
	}
	checkHTTP(before)
	t.Logf("Selected a quiet window        tmux=%d  observed=%d", rawSwitch, switched.Activity.at)

	send("foreground", "new background output")
	updated := waitForSample(time.Now())
	rawOutput := rawInt(sessionRow().LastActivity)
	if updated.Activity.at != rawOutput || rawOutput <= rawSwitch {
		t.Fatalf("background output: raw = %d, confirmed = %d, switch = %d", rawOutput, updated.Activity.at, rawSwitch)
	}
	checkHTTP(rawOutput)
	t.Logf("New output in the background   tmux=%d  observed=%d", rawOutput, updated.Activity.at)
	t.Log("Flat list, tree, overview, and project timestamps agree.")
}
