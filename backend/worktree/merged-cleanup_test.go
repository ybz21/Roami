package worktree

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestRemoveMergedRechecksConfirmedCheckout(t *testing.T) {
	ctx := context.Background()
	repo := mkRepo(t)
	service := New(t.TempDir(), nil)
	run := func(dir string, args ...string) {
		t.Helper()
		if out, err := gitID(ctx, dir, args...); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	create := func(branch string, adopted bool) (CreateResp, string) {
		t.Helper()
		if adopted {
			run(repo, "branch", branch)
		}
		wt, err := service.Create(ctx, CreateReq{Dir: repo, Branch: branch, Base: "main", Existing: adopted})
		if err != nil {
			t.Fatal(err)
		}
		commitFile(t, wt.Path, branch+".txt", branch+"\n", branch)
		head, err := service.Head(ctx, wt.Path)
		if err != nil {
			t.Fatal(err)
		}
		return wt, head
	}
	reject := func(wt CreateResp, branch, head, code string) {
		t.Helper()
		_, err := service.RemoveMerged(ctx, wt.Path, branch, head)
		var failure *Err
		if !errors.As(err, &failure) || failure.Code != code {
			t.Fatalf("expected %s, got %v", code, err)
		}
		if _, err := os.Stat(wt.Path); err != nil {
			t.Fatalf("protected worktree did not survive: %v", err)
		}
	}

	wt, head := create("landed", false)
	reject(wt, wt.Branch, head, "WORKTREE_NOT_MERGED")
	run(repo, "merge", "--squash", wt.Branch)
	run(repo, "commit", "-m", "squash landed")
	run(repo, "fetch", "origin")
	reject(wt, wt.Branch, wt.StartOid, "WORKTREE_CHANGED")
	reject(wt, "old-name", head, "WORKTREE_CHANGED")

	pending := filepath.Join(wt.Path, "pending.txt")
	if err := os.WriteFile(pending, []byte("keep me"), 0o644); err != nil {
		t.Fatal(err)
	}
	reject(wt, wt.Branch, head, "WORKTREE_DIRTY")
	if err := os.Remove(pending); err != nil {
		t.Fatal(err)
	}
	cleaned, err := service.RemoveMerged(ctx, wt.Path, wt.Branch, head)
	if err != nil || cleaned.MergedKind != "squash" {
		t.Fatalf("squash cleanup = %+v, %v", cleaned, err)
	}
	if _, err := os.Stat(wt.Path); !os.IsNotExist(err) {
		t.Fatalf("worktree removal: %v", err)
	}
	if branchExists(ctx, Repo{Root: repo}, wt.Branch) {
		t.Fatal("cleaned branch survived")
	}

	adopted, head := create("adopted", true)
	run(repo, "merge", "--ff-only", adopted.Branch)
	run(repo, "fetch", "origin")
	if _, err := service.RemoveMerged(ctx, adopted.Path, adopted.Branch, head); err != nil {
		t.Fatal(err)
	}
	if !branchExists(ctx, Repo{Root: repo}, adopted.Branch) {
		t.Fatal("adopted branch was removed")
	}
}
