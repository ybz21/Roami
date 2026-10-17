package worktree

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestExplicitBaseFetchesNewRemoteCommit(t *testing.T) {
	repo := mkRepo(t)
	run := func(dir string, args ...string) string {
		t.Helper()
		c := exec.Command("git", append([]string{"-C", dir}, args...)...)
		c.Env = scrubGitEnv()
		out, e := c.CombinedOutput()
		if e != nil {
			t.Fatalf("git %v: %s %v", args, out, e)
		}
		return strings.TrimSpace(string(out))
	}
	remote := filepath.Join(t.TempDir(), "remote.git")
	run(repo, "clone", "--bare", repo, remote)
	run(repo, "remote", "set-url", "origin", remote)
	clone := filepath.Join(t.TempDir(), "clone")
	run(repo, "clone", remote, clone)
	commitFile(t, clone, "remote.txt", "new", "remote advance")
	want := run(clone, "rev-parse", "HEAD")
	run(clone, "push", "origin", "main")
	old := run(repo, "rev-parse", "HEAD")
	s := New("", nil)
	wt, e := s.Create(context.Background(), CreateReq{Dir: repo, Branch: "fresh", Base: "main"})
	if e != nil {
		t.Fatal(e)
	}
	if got := run(wt.Path, "rev-parse", "HEAD"); got != want {
		t.Fatalf("HEAD=%s want remote=%s", got, want)
	}
	if run(repo, "rev-parse", "main") != old {
		t.Fatal("local main moved")
	}
	if refs := run(repo, "for-each-ref", "--format=%(refname)", "refs/roami/prepares"); refs != "" {
		t.Fatalf("temporary refs leaked: %s", refs)
	}
}
func TestFetchFailureDoesNotCreateStaleWorktree(t *testing.T) {
	repo := mkRepo(t)
	cmd := exec.Command("git", "-C", repo, "remote", "set-url", "origin", filepath.Join(t.TempDir(), "absent.git"))
	cmd.Env = scrubGitEnv()
	if b, e := cmd.CombinedOutput(); e != nil {
		t.Fatalf("setup: %v %s", e, b)
	}
	s := New("", nil)
	_, e := s.Create(context.Background(), CreateReq{Dir: repo, Branch: "should-not-exist", Base: "main"})
	if e == nil || !strings.Contains(e.Error(), "FETCH_FAILED") {
		t.Fatalf("expected FETCH_FAILED, got %v", e)
	}
	if files, _ := os.ReadDir(filepath.Join(repo, ".worktrees")); len(files) > 0 {
		t.Fatal("failed fetch created a worktree")
	}
	cmd = exec.Command("git", "-C", repo, "show-ref", "--verify", "refs/heads/should-not-exist")
	cmd.Env = scrubGitEnv()
	if cmd.Run() == nil {
		t.Fatal("failed fetch created a branch")
	}
}
