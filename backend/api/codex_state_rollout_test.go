package api

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestPickCodexStateRolloutResumedFromAnotherDirectory(t *testing.T) {
	db, err := sql.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec(`CREATE TABLE threads (rollout_path TEXT, cwd TEXT, archived INTEGER, updated_at_ms INTEGER)`); err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	rollout := filepath.Join(root, "2026", "10", "08", "rollout-old.jsonl")
	if err := os.MkdirAll(filepath.Dir(rollout), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(rollout, []byte(`{"type":"session_meta","payload":{"cwd":"/repo"}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	started := time.Date(2026, 10, 22, 16, 0, 0, 0, time.UTC)
	insert := func(path, cwd string, archived int, updated time.Time) {
		t.Helper()
		if _, err := db.Exec(`INSERT INTO threads VALUES (?,?,?,?)`, path, cwd, archived, updated.UnixMilli()); err != nil {
			t.Fatal(err)
		}
	}
	insert(rollout, "/repo/.worktrees/task", 0, started.Add(time.Minute))
	insert(rollout, "/repo/.worktrees/task", 1, started.Add(time.Hour))
	insert(rollout, "/repo/.worktrees/other", 0, started.Add(time.Hour))
	if got := pickCodexStateRollout(db, "/repo/.worktrees/task", started, root); got != rollout {
		t.Fatalf("恢复旧目录的对话 = %q, want %q", got, rollout)
	}
	insert(rollout, "/repo/.worktrees/task", 0, started.Add(time.Hour))
	if got := pickCodexStateRollout(db, "/repo/.worktrees/task", started, root); got != "" {
		t.Fatalf("同目录多个活跃对话不能猜: %q", got)
	}
}

func TestPickCodexStateRolloutRejectsStaleAndExternal(t *testing.T) {
	db, err := sql.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec(`CREATE TABLE threads (rollout_path TEXT, cwd TEXT, archived INTEGER, updated_at_ms INTEGER)`); err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	outside := filepath.Join(t.TempDir(), "rollout.jsonl")
	if err := os.WriteFile(outside, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	started := time.Date(2026, 10, 22, 16, 0, 0, 0, time.UTC)
	if _, err := db.Exec(`INSERT INTO threads VALUES (?,?,?,?)`, outside, "/repo", 0, started.Add(time.Hour).UnixMilli()); err != nil {
		t.Fatal(err)
	}
	if got := pickCodexStateRollout(db, "/repo", started, root); got != "" {
		t.Fatalf("不能读取会话目录外的文件: %q", got)
	}
	if _, err := db.Exec(`DELETE FROM threads`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO threads VALUES (?,?,?,?)`, outside, "/repo", 0, started.Add(-time.Hour).UnixMilli()); err != nil {
		t.Fatal(err)
	}
	if got := pickCodexStateRollout(db, "/repo", started, root); got != "" {
		t.Fatalf("不能认领进程启动前的旧对话: %q", got)
	}
}

func TestCodexStateRolloutReadsCurrentStateDatabase(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	dir := filepath.Join(home, ".codex")
	if err := os.MkdirAll(filepath.Join(dir, "sessions"), 0o700); err != nil {
		t.Fatal(err)
	}
	rollout := filepath.Join(dir, "sessions", "rollout-old.jsonl")
	if err := os.WriteFile(rollout, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	db, err := sql.Open("sqlite", filepath.Join(dir, "state_5.sqlite"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`CREATE TABLE threads (rollout_path TEXT, cwd TEXT, archived INTEGER, updated_at_ms INTEGER)`); err != nil {
		t.Fatal(err)
	}
	started := time.Date(2026, 10, 22, 16, 0, 0, 0, time.UTC)
	if _, err := db.Exec(`INSERT INTO threads VALUES (?,?,?,?)`, rollout, "/repo/.worktrees/task", 0, started.Add(time.Minute).UnixMilli()); err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	if got := codexStateRollout("/repo/.worktrees/task", started); got != rollout {
		t.Fatalf("state 数据库中的恢复会话 = %q, want %q", got, rollout)
	}
}
