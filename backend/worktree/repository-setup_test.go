package worktree

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestInitializeRepositorySnapshotsFilesAndCreatesLocalWorktree(t *testing.T) {
	t.Setenv("GIT_CONFIG_GLOBAL", "/dev/null")
	t.Setenv("GIT_CONFIG_SYSTEM", "/dev/null")
	t.Setenv("GIT_AUTHOR_NAME", "")
	t.Setenv("GIT_AUTHOR_EMAIL", "")
	ctx := context.Background()
	s := New("", nil)
	dir := t.TempDir()
	for name, content := range map[string]string{"app.txt": "project content", ".gitignore": "ignored.txt\n", "ignored.txt": "local only"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0600); err != nil {
			t.Fatal(err)
		}
	}
	state, err := s.RepositoryState(ctx, dir)
	if err != nil || state.Repo {
		t.Fatalf("before: %+v %v", state, err)
	}
	state, err = s.InitializeRepository(ctx, dir)
	if err != nil || !state.Repo || !state.HasCommits {
		t.Fatalf("initialize: %+v %v", state, err)
	}
	files, _ := git(ctx, dir, "ls-files")
	if strings.Contains(files, "ignored.txt") || !strings.Contains(files, "app.txt") {
		t.Fatalf("snapshot files: %s", files)
	}
	head, _ := git(ctx, dir, "rev-parse", "HEAD")
	wt, err := s.Create(ctx, CreateReq{Dir: dir, Branch: "feat/first-task"})
	if err != nil {
		t.Fatal(err)
	}
	if content, err := os.ReadFile(filepath.Join(wt.Path, "app.txt")); err != nil || string(content) != "project content" {
		t.Fatalf("worktree content: %s %v", content, err)
	}
	if wt.Base != "main" || wt.StartOid != head {
		t.Fatalf("base: %+v", wt)
	}
	if err := os.WriteFile(filepath.Join(dir, "app.txt"), []byte("uncommitted change"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.InitializeRepository(ctx, dir); err != nil {
		t.Fatal(err)
	}
	if got, _ := git(ctx, dir, "rev-parse", "HEAD"); got != head {
		t.Fatal("repeat initialization committed user changes")
	}
}

func TestInitializeUnbornRepositoryPreservesBranchAndCanRetry(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	dir := t.TempDir()
	if out, err := git(ctx, dir, "init", "-b", "develop"); err != nil {
		t.Fatalf("init: %s %v", out, err)
	}
	if err := os.WriteFile(filepath.Join(dir, "app.txt"), []byte("content"), 0600); err != nil {
		t.Fatal(err)
	}
	hook := filepath.Join(dir, ".git", "hooks", "pre-commit")
	if err := os.WriteFile(hook, []byte("#!/bin/sh\nexit 1\n"), 0700); err != nil {
		t.Fatal(err)
	}
	if _, err := s.InitializeRepository(ctx, dir); err == nil {
		t.Fatal("expected commit hook failure")
	}
	state, err := s.RepositoryState(ctx, dir)
	if err != nil || !state.Repo || state.HasCommits {
		t.Fatalf("failed setup state: %+v %v", state, err)
	}
	if _, err := os.Stat(filepath.Join(dir, "app.txt")); err != nil {
		t.Fatal("project file lost")
	}
	if err := os.Remove(hook); err != nil {
		t.Fatal(err)
	}
	state, err = s.InitializeRepository(ctx, dir)
	if err != nil || !state.HasCommits {
		t.Fatalf("retry: %+v %v", state, err)
	}
	if branch, _ := git(ctx, dir, "branch", "--show-current"); branch != "develop" {
		t.Fatalf("branch changed: %s", branch)
	}
	if _, err = s.Create(ctx, CreateReq{Dir: dir, Branch: "task", Base: "develop"}); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Create(ctx, CreateReq{Dir: dir, Branch: "bad", Base: "absent"}); err == nil {
		t.Fatal("accepted nonexistent local base")
	}
}

func TestRepositorySetupBoundaries(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	for _, dir := range []string{"relative", filepath.Join(t.TempDir(), "absent")} {
		if _, err := s.InitializeRepository(ctx, dir); err == nil {
			t.Fatalf("accepted %s", dir)
		}
	}
	dir := t.TempDir()
	if _, err := git(ctx, dir, "init", "-b", "main"); err != nil {
		t.Fatal(err)
	}
	sub := filepath.Join(dir, "sub")
	if err := os.Mkdir(sub, 0700); err != nil {
		t.Fatal(err)
	}
	if _, err := s.InitializeRepository(ctx, sub); err == nil || !strings.Contains(err.Error(), "INIT_ROOT_REQUIRED") {
		t.Fatalf("nested repair: %v", err)
	}
	corrupt := t.TempDir()
	if err := os.WriteFile(filepath.Join(corrupt, ".git"), []byte("invalid gitfile"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.InitializeRepository(ctx, corrupt); err == nil {
		t.Fatal("overwrote corrupt repository")
	}
	empty := t.TempDir()
	if state, err := s.InitializeRepository(ctx, empty); err != nil || !state.HasCommits {
		t.Fatalf("empty directory: %+v %v", state, err)
	}
}
