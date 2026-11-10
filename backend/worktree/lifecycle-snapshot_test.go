package worktree

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestLifecycleCreateRecoversOwnedDirectoryWithoutAllocatingAnother(t *testing.T) {
	s := New("", nil)
	repo := mkRepo(t)
	ctx := context.Background()
	req := CreateReq{Dir: repo, Branch: "task", Dirname: "reserved-session", OperationID: "operation-one"}
	first, err := s.Create(ctx, req)
	if err != nil {
		t.Fatal(err)
	}
	again, err := s.Create(ctx, req)
	if err != nil || again != first {
		t.Fatalf("did not observe existing result: %+v %+v %v", first, again, err)
	}
	req.OperationID = "operation-two"
	if _, err = s.Create(ctx, req); err == nil {
		t.Fatal("another operation adopted the old directory")
	}
	if _, err = os.Stat(first.Path + "-2"); !os.IsNotExist(err) {
		t.Fatalf("leaked another worktree: %v", err)
	}
}

func TestLifecycleSnapshotDetectsNewIgnoredContentAndBranchRename(t *testing.T) {
	s := New("", nil)
	repo := mkRepo(t)
	ctx := context.Background()
	wt, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "task"})
	if err != nil {
		t.Fatal(err)
	}
	first, err := s.Snapshot(ctx, wt.Path)
	if err != nil {
		t.Fatal(err)
	}
	again, err := s.Snapshot(ctx, wt.Path)
	if err != nil || first != again {
		t.Fatalf("read changed snapshot: %s %s %v", first, again, err)
	}
	if err = os.WriteFile(filepath.Join(wt.Path, "new-ignored-file"), []byte("later writer"), 0600); err != nil {
		t.Fatal(err)
	}
	changed, err := s.Snapshot(ctx, wt.Path)
	if err != nil || changed == first {
		t.Fatal("new file was not detected")
	}
	if err = os.Remove(filepath.Join(wt.Path, "new-ignored-file")); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GIT_DIR", filepath.Join(repo, ".git"))
	t.Setenv("GIT_WORK_TREE", repo)
	cmd := exec.Command("git", "-C", wt.Path, "branch", "-m", "renamed")
	cmd.Env = scrubGitEnv()
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("rename: %v %s", err, out)
	}
	renamed, err := s.Snapshot(ctx, wt.Path)
	if err != nil || renamed == first {
		t.Fatal("branch rename was not detected")
	}
}

func TestLifecycleRemoveRejectsLaterWritesAndAdoptedBranchSurvives(t *testing.T) {
	s := New("", nil)
	repo := mkRepo(t)
	ctx := context.Background()
	wt, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "task"})
	if err != nil {
		t.Fatal(err)
	}
	snapshot, err := s.Snapshot(ctx, wt.Path)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(wt.Path, "later.txt"), []byte("keep me"), 0600); err != nil {
		t.Fatal(err)
	}
	// Snapshot validation happens before even attempting to observe or remove resources.
	err = s.Remove(ctx, RemoveReq{Path: wt.Path, ExpectedSnapshot: snapshot, ForceWorktree: true})
	var we *Err
	if !errors.As(err, &we) || we.Code != "LIFECYCLE_WORKSPACE_CHANGED" {
		t.Fatalf("unexpected protection: %v", err)
	}
	if _, err = os.Stat(filepath.Join(wt.Path, "later.txt")); err != nil {
		t.Fatal("later content was removed")
	}
}

func TestLifecycleSnapshotDetectsContentEvenWhenSizeAndTimestampArePreserved(t *testing.T) {
	service := New("", nil)
	repo := mkRepo(t)
	ctx := context.Background()
	wt, err := service.Create(ctx, CreateReq{Dir: repo, Branch: "snapshot-content"})
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(wt.Path, "untracked.txt")
	if err = os.WriteFile(path, []byte("before"), 0600); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	before, err := service.Snapshot(ctx, wt.Path)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, []byte("after!"), 0600); err != nil {
		t.Fatal(err)
	}
	if err = os.Chtimes(path, info.ModTime(), info.ModTime()); err != nil {
		t.Fatal(err)
	}
	after, err := service.Snapshot(ctx, wt.Path)
	if err != nil || before == after {
		t.Fatalf("content-only change was missed: %v", err)
	}
}

func TestLifecycleSnapshotAndDetailsSupportDetachedHead(t *testing.T) {
	service := New("", nil)
	ctx := context.Background()
	repo := mkRepo(t)
	wt, err := service.Create(ctx, CreateReq{Dir: repo, Branch: "detached-cleanup"})
	if err != nil {
		t.Fatal(err)
	}
	attached, err := service.Snapshot(ctx, wt.Path)
	if err != nil {
		t.Fatal(err)
	}
	if out, err := git(ctx, wt.Path, "checkout", "--detach", "HEAD"); err != nil {
		t.Fatalf("detach: %v %s", err, out)
	}
	state, err := service.SnapshotState(ctx, wt.Path)
	if err != nil || state.Fingerprint == "" || state.Fingerprint == attached || state.Branch != "" || !state.Clean {
		t.Fatalf("detached confirmation: %+v %v", state, err)
	}
	details, err := service.LifecycleDetails(ctx, wt.Path)
	if err != nil || details.Branch != "" || details.Head != state.Head || details.External {
		t.Fatalf("detached identity: %+v %v", details, err)
	}
	if err := os.WriteFile(filepath.Join(wt.Path, "late-file"), []byte("retained"), 0600); err != nil {
		t.Fatal(err)
	}
	after, err := service.Snapshot(ctx, wt.Path)
	if err != nil || after == state.Fingerprint {
		t.Fatalf("detached write was missed: %v", err)
	}
}
