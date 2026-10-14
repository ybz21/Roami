package api

import (
	"context"
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
