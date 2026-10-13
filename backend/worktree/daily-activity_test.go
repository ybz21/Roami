package worktree

import (
	"context"
	"os/exec"
	"testing"
	"time"
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

func TestActivityCommitsFiltersOldDatesWithoutSkippingRecentAncestors(t *testing.T) {
	dir := mkRepo(t)
	commitFile(t, dir, "old.txt", "old", "backdated")
	old := time.Now().AddDate(0, 0, -500).Format(time.RFC3339)
	cmd := exec.Command("git", "-C", dir, "commit", "--amend", "--no-edit", "--date="+old)
	cmd.Env = append(scrubGitEnv(), "GIT_COMMITTER_DATE="+old,
		"GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@t", "GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@t")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("backdate: %v %s", err, out)
	}
	commitFile(t, dir, "recent.txt", "recent", "recent")
	s := New("", nil)
	repo, err := s.ResolveRepo(context.Background(), dir)
	if err != nil {
		t.Fatal(err)
	}
	commits, err := s.ActivityCommits(context.Background(), repo)
	if err != nil {
		t.Fatal(err)
	}
	if len(commits) != 2 {
		t.Fatalf("want both recent commits across the backdated commit, got %d", len(commits))
	}
	for _, commit := range commits {
		if commit.At < time.Now().AddDate(0, 0, -370).Unix() {
			t.Fatalf("backdated commit included: %+v", commit)
		}
	}
}
