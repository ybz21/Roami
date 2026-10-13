package worktree

import (
	"context"
	"testing"
)

func TestActivityCommitsIncludesBranchesWithoutMerges(t *testing.T) {
	ctx := context.Background()
	dir := mkRepo(t)
	s := New("", nil)
	if _, err := git(ctx, dir, "checkout", "-b", "feature"); err != nil {
		t.Fatal(err)
	}
	commitFile(t, dir, "feature.txt", "feature", "feature")
	if _, err := git(ctx, dir, "checkout", "main"); err != nil {
		t.Fatal(err)
	}
	commitFile(t, dir, "main.txt", "main", "main")
	if _, err := gitID(ctx, dir, "merge", "--no-ff", "feature", "-m", "merge"); err != nil {
		t.Fatal(err)
	}
	repo, err := s.ResolveRepo(ctx, dir)
	if err != nil {
		t.Fatal(err)
	}
	commits, err := s.ActivityCommits(ctx, repo)
	if err != nil {
		t.Fatal(err)
	}
	if len(commits) != 3 {
		t.Fatalf("want three unique non-merge commits, got %d", len(commits))
	}
	for _, commit := range commits {
		if len(commit.OID) != 40 || commit.At <= 0 {
			t.Fatalf("invalid commit: %+v", commit)
		}
	}
}
