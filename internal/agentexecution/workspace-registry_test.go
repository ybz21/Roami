package agentexecution

import (
	"context"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/ybz21/Roami/backend/project"
	"github.com/ybz21/Roami/internal/gitcontext"
)

func TestDirectoryWorkspaceIdentityScopeAndStaleReuse(t *testing.T) {
	s := testService(t)
	db, err := s.platform(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	store := project.NewStore(s.Runtime.DataDir, db)
	directory := t.TempDir()
	id, _ := store.Add(directory, "first")
	other, _ := store.Add(t.TempDir(), "other")
	workspace, err := s.prepareWorkspace(context.Background(), Spec{ProjectID: id}, "unused")
	if err != nil || workspace.ID == "" {
		t.Fatalf("registration: %+v %v", workspace, err)
	}
	again, err := s.prepareWorkspace(context.Background(), Spec{ProjectID: id, WorkspaceID: workspace.ID}, "other-launch")
	if err != nil || again != workspace {
		t.Fatalf("reuse: %+v %v", again, err)
	}
	_, err = s.prepareWorkspace(context.Background(), Spec{ProjectID: other, WorkspaceID: workspace.ID}, "other-launch")
	if err == nil || err.Error() != "WORKSPACE_PROJECT_MISMATCH" {
		t.Fatalf("cross-project reuse: %v", err)
	}
	_, err = s.prepareWorkspace(context.Background(), Spec{ProjectID: id, WorkspaceID: "../../elsewhere"}, "other-launch")
	if err == nil || err.Error() != "UNKNOWN_WORKSPACE" {
		t.Fatalf("path used as identity: %v", err)
	}
	if err = os.Rename(directory, directory+"-moved"); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(directory + "-moved") })
	_, err = s.prepareWorkspace(context.Background(), Spec{ProjectID: id, WorkspaceID: workspace.ID}, "other-launch")
	if err == nil || err.Error() != "WORKSPACE_STALE" {
		t.Fatalf("stale reuse fell back: %v", err)
	}
}

func TestWorkspaceWriterExclusionQuarantineAndConfirmedRelease(t *testing.T) {
	s := testService(t)
	directory := t.TempDir()
	release, err := s.claimWorkspace(context.Background(), directory, "first")
	if err != nil {
		t.Fatal(err)
	}
	_, err = s.claimWorkspace(context.Background(), directory, "concurrent")
	if err == nil || err.Error() != "WORKSPACE_BUSY" {
		t.Fatalf("writer overlap: %v", err)
	}
	release()
	// A dead lock holder does not prove the coding process stopped.
	_, err = s.claimWorkspace(context.Background(), directory, "after-crash")
	if err == nil || err.Error() != "WORKSPACE_OUTCOME_UNKNOWN" {
		t.Fatalf("lost runner replayed: %v", err)
	}
	dir, _ := s.directory("first")
	if err = os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err = writeJSON(filepath.Join(dir, "result.json"), Result{State: "cancelled", FinishedMS: time.Now().UnixMilli()}); err != nil {
		t.Fatal(err)
	}
	release, err = s.claimWorkspace(context.Background(), directory, "after-confirmed-stop")
	if err != nil {
		t.Fatal(err)
	}
	release()
}

func TestWorkspaceWriterAliasesShareTheSameLease(t *testing.T) {
	s := testService(t)
	directory := t.TempDir()
	alias := filepath.Join(t.TempDir(), "alias")
	if err := os.Symlink(directory, alias); err != nil {
		t.Fatal(err)
	}
	release, err := s.claimWorkspace(context.Background(), directory, "canonical")
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	_, err = s.claimWorkspace(context.Background(), alias, "symlink")
	if err == nil || err.Error() != "WORKSPACE_BUSY" {
		t.Fatalf("symlink bypassed writer: %v", err)
	}
}

func TestBusyWorkspaceRecordsFailureBeforeCodingProcessStarts(t *testing.T) {
	s := testService(t)
	directory := t.TempDir()
	release, err := s.claimWorkspace(context.Background(), directory, "first")
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	dir, _ := s.directory("rejected-writer")
	if err = os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	spec := Spec{Key: "rejected-writer", Executor: "codex", Directory: directory, Prompt: "must not run", TimeoutSeconds: 10}
	if err = writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
		t.Fatal(err)
	}
	if err = writeJSON(filepath.Join(dir, "receipt.json"), Receipt{State: "launched"}); err != nil {
		t.Fatal(err)
	}
	if err = s.Run(context.Background(), spec.Key, io.Discard, io.Discard); err != nil {
		t.Fatal(err)
	}
	var result Result
	if err = readJSON(filepath.Join(dir, "result.json"), &result); err != nil {
		t.Fatal(err)
	}
	if result.State != "failed" || result.Summary != "WORKSPACE_BUSY" {
		t.Fatalf("rejected writer: %+v", result)
	}
}

func TestNestedCheckoutDirectoriesShareLeaseButLinkedWorktreesDoNot(t *testing.T) {
	s := testService(t)
	repo := t.TempDir()
	run := func(args ...string) {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", repo}, args...)...)
		cmd.Env = append(gitcontext.ForDirectory(os.Environ()), "GIT_AUTHOR_NAME=Fixture", "GIT_AUTHOR_EMAIL=fixture@example.invalid", "GIT_COMMITTER_NAME=Fixture", "GIT_COMMITTER_EMAIL=fixture@example.invalid")
		if output, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, output)
		}
	}
	run("init", "-b", "main")
	run("commit", "--allow-empty", "-m", "initial")
	first, second := filepath.Join(repo, "a"), filepath.Join(repo, "b")
	if err := os.MkdirAll(first, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(second, 0700); err != nil {
		t.Fatal(err)
	}
	linked := filepath.Join(t.TempDir(), "linked")
	run("worktree", "add", "-b", "worker", linked)
	release, err := s.claimWorkspace(context.Background(), first, "nested-first")
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	_, err = s.claimWorkspace(context.Background(), second, "nested-second")
	if err == nil || err.Error() != "WORKSPACE_BUSY" {
		t.Fatalf("nested directory bypassed exclusion: %v", err)
	}
	releaseLinked, err := s.claimWorkspace(context.Background(), linked, "independent-checkout")
	if err != nil {
		t.Fatalf("independent worktree was blocked: %v", err)
	}
	releaseLinked()
}
