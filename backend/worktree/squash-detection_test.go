package worktree

import (
	"context"
	"path/filepath"
	"strings"
	"testing"
)

func TestCombinedSquashDetection(t *testing.T) {
	for _, kind := range []string{"text", "binary", "rename"} {
		t.Run(kind, func(t *testing.T) {
			ctx := context.Background()
			s := New("", nil)
			repo := mkRepo(t)
			run := func(dir string, args ...string) string {
				t.Helper()
				out, err := gitID(ctx, dir, args...)
				if err != nil {
					t.Fatalf("git %v: %v %s", args, err, out)
				}
				return strings.TrimSpace(out)
			}
			wt, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "feature", Base: "main"})
			if err != nil {
				t.Fatal(err)
			}
			commitFile(t, wt.Path, "feature", "first\n", "first")
			partial := run(wt.Path, "rev-parse", "HEAD")
			commitFile(t, wt.Path, "feature", "revised\n", "revise")
			switch kind {
			case "text":
				commitFile(t, wt.Path, "another", "another\n", "another")
			case "binary":
				commitFile(t, wt.Path, "binary", "\x00\x01\x02\xff", "binary")
			case "rename":
				run(wt.Path, "mv", "a.txt", "renamed.txt")
				run(wt.Path, "commit", "-m", "rename")
			}
			head := run(wt.Path, "rev-parse", "HEAD")
			run(repo, "remote", "remove", "origin")
			inspect := func() Worktree {
				t.Helper()
				s.invalidate(Repo{CommonDir: filepath.Join(repo, ".git")})
				list, err := s.List(ctx, repo)
				if err != nil {
					t.Fatal(err)
				}
				for _, w := range list {
					if w.Path == wt.Path {
						return w
					}
				}
				t.Fatal("missing feature worktree")
				return Worktree{}
			}
			// A partial landing and unrelated target commits must not authorize cleanup.
			commitFile(t, repo, "before", "unrelated\n", "before")
			run(repo, "cherry-pick", partial)
			if w := inspect(); w.MergedInto != "" || w.AheadUnique == 0 {
				t.Fatalf("partial squash reported merged: %+v", w)
			}
			// Remove only the disposable fixture's partial landing before the full squash.
			run(repo, "revert", "--no-edit", "HEAD")
			run(repo, "merge", "--squash", "feature")
			run(repo, "commit", "-m", "squash feature")
			commitFile(t, repo, "after", "unrelated\n", "after")
			if w := inspect(); w.MergedInto != "main" || w.MergedKind != "squash" || w.AheadUnique != 0 || w.CommittedAhead != 3 {
				t.Fatalf("combined squash missing after target advanced: %+v", w)
			}
			commitFile(t, wt.Path, "followup", "unmerged\n", "followup")
			if w := inspect(); w.MergedInto != "" || w.AheadUnique == 0 {
				t.Fatalf("followup commit reported merged: %+v", w)
			}
			if run(wt.Path, "rev-parse", "HEAD^") != head || run(wt.Path, "status", "--porcelain") != "" {
				t.Fatal("merge detection changed the source worktree")
			}
		})
	}
}

func TestCombinedSquashEmptyPatch(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)
	wt, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "empty-patch", Base: "main"})
	if err != nil {
		t.Fatal(err)
	}
	commitFile(t, wt.Path, "a.txt", "changed\n", "change")
	commitFile(t, wt.Path, "a.txt", "hello\n", "undo")
	commitFile(t, repo, "unrelated", "unrelated\n", "unrelated")
	w, err := s.ClosePreflight(ctx, wt.Path)
	if err != nil || w.MergedInto != "" || w.CommittedAhead != 2 {
		t.Fatalf("empty combined patch is not merge evidence: %+v %v", w, err)
	}
}

func TestPatchIDsFailure(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if ids, err := patchIDs(ctx, mkRepo(t), "log", "-p"); err == nil || len(ids) != 0 {
		t.Fatalf("canceled patch comparison succeeded: %v %v", ids, err)
	}
	if ids, err := patchIDs(context.Background(), t.TempDir(), "log", "-p"); err == nil || len(ids) != 0 {
		t.Fatalf("failed git producer succeeded: %v %v", ids, err)
	}
}
