package api

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"testing"
	"time"

	"ttmux-web/worktree"
)

func TestGitFootprintsBackfillIsDurableAndIdempotent(t *testing.T) {
	dir := t.TempDir()
	ctx := context.Background()
	now := time.Now().Unix()
	commits := []worktree.ActivityCommit{{OID: "recent", At: now}, {OID: "old", At: time.Now().AddDate(0, 0, -500).Unix()}}
	s := NewGitFootprintStore(dir)
	if err := s.Import(ctx, commits); err != nil {
		t.Fatal(err)
	}
	if err := s.Import(ctx, commits); err != nil {
		t.Fatal(err)
	}
	var n int
	if err := s.db.QueryRow(`SELECT count(*) FROM git_commits`).Scan(&n); err != nil || n != 2 {
		t.Fatalf("archive count=%d err=%v", n, err)
	}
	s.db.Close()
	s = NewGitFootprintStore(dir)
	defer s.db.Close()
	recent, err := s.Recent(ctx)
	if err != nil || len(recent) != 1 || recent[0].OID != "recent" {
		t.Fatalf("reopened history=%v err=%v", recent, err)
	}
	if err := s.Import(ctx, nil); err != nil {
		t.Fatal(err)
	}
	recent, err = s.Recent(ctx)
	if err != nil || len(recent) != 1 {
		t.Fatalf("history lost after empty scan: %v %v", recent, err)
	}
}

func TestGitFootprintsImportRollsBackOnCancellation(t *testing.T) {
	s := NewGitFootprintStore(t.TempDir())
	defer s.db.Close()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := s.Import(ctx, []worktree.ActivityCommit{{OID: "cancelled", At: time.Now().Unix()}}); err == nil {
		t.Fatal("expected cancellation error")
	}
	recent, err := s.Recent(context.Background())
	if err != nil || len(recent) != 0 {
		t.Fatalf("cancelled import wrote history: %v %v", recent, err)
	}
}

func TestGitFootprintsReportsUnwritableArchive(t *testing.T) {
	path := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(path, []byte("file"), 0600); err != nil {
		t.Fatal(err)
	}
	s := NewGitFootprintStore(path)
	if err := s.Import(context.Background(), nil); err == nil {
		t.Fatal("expected archive error")
	}
}

func TestGitFootprintsUpgradesLegacyArchiveWithoutChangingCounts(t *testing.T) {
	dir := t.TempDir()
	db, err := sql.Open("sqlite", "file:"+filepath.Join(dir, "ai-footprints.db"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`CREATE TABLE git_commits(oid TEXT PRIMARY KEY, at INTEGER NOT NULL); INSERT INTO git_commits VALUES ('existing', 12345)`); err != nil {
		t.Fatal(err)
	}
	db.Close()
	s := NewGitFootprintStore(dir)
	defer s.db.Close()
	commit := worktree.ActivityCommit{OID: "existing", At: 12345, Repo: "/projects/app", Subject: "Fix login"}
	for i := 0; i < 2; i++ {
		if err := s.Import(context.Background(), []worktree.ActivityCommit{commit}); err != nil {
			t.Fatal(err)
		}
	}
	records, err := s.Day(context.Background(), 12345, 12346)
	if err != nil || len(records) != 1 || records[0].Subject != "Fix login" || records[0].Repo != "/projects/app" {
		t.Fatalf("upgraded day=%v err=%v", records, err)
	}
	next, err := s.Day(context.Background(), 12346, 12347)
	if err != nil || len(next) != 0 {
		t.Fatalf("day boundary=%v err=%v", next, err)
	}
}
