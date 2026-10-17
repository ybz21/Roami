package swarm

import (
	"database/sql"
	metadb "github.com/ybz21/Roami/internal/storage"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	_ "modernc.org/sqlite"
)

func TestStatusJSONCompat(t *testing.T) {
	root := t.TempDir()
	home := filepath.Join(root, "home")
	data := filepath.Join(root, "data")
	if err := os.MkdirAll(filepath.Join(home, "swarms", "sw1", "listeners"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(home, "swarms", "sw1", "busy"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(data, "logs"), 0o755); err != nil {
		t.Fatal(err)
	}
	writeMeta(t, filepath.Join(home, "meta.db"))
	writeSwarm(t, filepath.Join(home, "swarms", "sw1", "swarm.db"))
	if err := os.WriteFile(filepath.Join(home, "swarms", "sw1", "listeners", "leader.last_post"), []byte("12\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	now := time.Unix(200, 0)
	if err := os.WriteFile(filepath.Join(home, "swarms", "sw1", "busy", "lead.busy"), []byte("180\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	tmux := writeFakeTmux(t, root)

	paths, e := metadb.ResolvePaths(home, data)
	if e != nil {
		t.Fatal(e)
	}
	if e = paths.MigrateLayout(true); e != nil {
		t.Fatal(e)
	}
	st, err := Status("case", Options{HomeDir: home, DataDir: data, TmuxBin: tmux, Now: func() time.Time { return now }})
	if err != nil {
		t.Fatal(err)
	}
	if st.Name != "case" || st.LeaderLastPost != 12 {
		t.Fatalf("unexpected status header: %+v", st)
	}
	got := map[string]SwarmMember{}
	for _, m := range st.Members {
		got[m.Name] = m
	}
	if got["lead"].Role != "leader" || got["web"].Role != "member" {
		t.Fatalf("roles not normalized: %+v", got)
	}
	if got["lead"].Status != "running" {
		t.Fatalf("busy leader should be running, got %q", got["lead"].Status)
	}
	if got["web"].Status != "idle" {
		t.Fatalf("web should be idle, got %q", got["web"].Status)
	}
	if got["api"].Status != "waiting" {
		t.Fatalf("api should be waiting, got %q", got["api"].Status)
	}
	if got["run"].Status != "running" {
		t.Fatalf("run should be running, got %q", got["run"].Status)
	}
	if len(st.Pending) != 1 || st.Pending[0].Name != "later" {
		t.Fatalf("unexpected pending: %+v", st.Pending)
	}
	if len(st.DoneMarked) != 1 || st.DoneMarked[0] != "done" {
		t.Fatalf("unexpected done list: %+v", st.DoneMarked)
	}
}

func writeMeta(t *testing.T, path string) {
	t.Helper()
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	_, err = db.Exec(`CREATE TABLE swarms(id TEXT PRIMARY KEY, name TEXT UNIQUE, goal TEXT, status TEXT, supervisor TEXT, created TEXT);
		INSERT INTO swarms(id,name,goal,status,supervisor,created) VALUES('sw1','case','goal','running','','2026-06-22 10:00:00');`)
	if err != nil {
		t.Fatal(err)
	}
}

func writeSwarm(t *testing.T, path string) {
	t.Helper()
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	_, err = db.Exec(`CREATE TABLE members(
		name TEXT PRIMARY KEY, type TEXT, task TEXT, deps TEXT, done INT DEFAULT 0, pending INT DEFAULT 0,
		kind TEXT DEFAULT 'claude', role TEXT DEFAULT 'member');
		INSERT INTO members(name,type,task,deps,done,pending,kind,role) VALUES
			('lead','agent','lead task','',0,0,'claude','master'),
			('web','agent','web task','',0,0,'claude','worker'),
			('api','agent','api task','',0,0,'codex','member'),
			('run','agent','run task','',0,0,'claude','member'),
			('done','agent','done task','',1,0,'claude','member'),
			('later','agent','later task','web',0,1,'claude','member');`)
	if err != nil {
		t.Fatal(err)
	}
}

func writeFakeTmux(t *testing.T, root string) string {
	t.Helper()
	path := filepath.Join(root, "tmux")
	script := `#!/usr/bin/env bash
case "$1" in
  has-session) exit 0 ;;
  display-message) echo 0; exit 0 ;;
  capture-pane)
    case "$*" in
      *case-api*) echo "Press ente"; exit 0 ;;
      *case-run*) echo "Puzzling"; exit 0 ;;
      *) echo ">"; exit 0 ;;
    esac
    ;;
esac
exit 0
`
	if err := os.WriteFile(path, []byte(strings.TrimLeft(script, "\n")), 0o755); err != nil {
		t.Fatal(err)
	}
	return path
}
