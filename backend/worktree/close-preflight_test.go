package worktree

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestClosePreflightEmptyWorktreeSkipsNetwork(t *testing.T) {
	s := New("", nil)
	repo := mkRepo(t)
	wt, err := s.Create(context.Background(), CreateReq{Dir: repo, Branch: "empty-close", Base: "main"})
	if err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(t.TempDir(), "attempt")
	ssh := filepath.Join(t.TempDir(), "ssh")
	if err := os.WriteFile(ssh, []byte("#!/bin/sh\ntouch '"+marker+"'\nexit 1\n"), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GIT_SSH_COMMAND", ssh)
	cmd := exec.Command("git", "-C", repo, "remote", "set-url", "origin", "ssh://unavailable.invalid/repo.git")
	cmd.Env = scrubGitEnv()
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("set origin: %v %s", err, out)
	}
	if err := os.WriteFile(filepath.Join(wt.Path, "draft"), []byte("unsaved"), 0600); err != nil {
		t.Fatal(err)
	}
	w, err := s.ClosePreflight(context.Background(), wt.Path)
	if err != nil || w.MergedInto != "" || w.Untracked != 1 {
		t.Fatalf("empty worktree lost draft state: %+v %v", w, err)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("empty worktree close attempted a network connection")
	}
}
