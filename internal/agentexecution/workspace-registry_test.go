package agentexecution

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/ybz21/Roami/backend/project"
	"github.com/ybz21/Roami/internal/gitcontext"
)

func TestWorkspaceReuseAfterTaskBranchCreationAndRenamePreservesProgress(t *testing.T) {
	s := testService(t)
	ctx := context.Background()
	repo := t.TempDir()
	git := func(directory string, args ...string) {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", directory}, args...)...)
		cmd.Env = append(gitcontext.ForDirectory(os.Environ()), "GIT_AUTHOR_NAME=Fixture", "GIT_AUTHOR_EMAIL=fixture@example.invalid", "GIT_COMMITTER_NAME=Fixture", "GIT_COMMITTER_EMAIL=fixture@example.invalid")
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	git(repo, "init", "-b", "main")
	git(repo, "commit", "--allow-empty", "-m", "initial")
	directory := filepath.Join(t.TempDir(), "task")
	git(repo, "worktree", "add", "-b", "agent/task", directory)
	db, err := s.platform(ctx)
	if err != nil {
		t.Fatal(err)
	}
	projectID, _ := project.NewStore(s.Runtime.DataDir, db).Add(repo, "fixture")
	cmd := exec.Command("git", "-C", directory, "rev-parse", "HEAD")
	cmd.Env = gitcontext.ForDirectory(os.Environ())
	oid, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	workspace, err := s.rememberWorkspace(Workspace{ProjectID: projectID, Directory: directory, Branch: "agent/task", StartOID: strings.TrimSpace(string(oid))})
	if err != nil {
		t.Fatal(err)
	}
	spec := Spec{ProjectID: projectID, WorkspaceID: workspace.ID}
	git(directory, "switch", "-c", "feat/task", workspace.StartOID)
	created, err := s.reuseWorkspace(ctx, spec)
	if err != nil || created.Branch != "feat/task" || created.ID != workspace.ID {
		t.Fatalf("task branch created in original workspace: %+v %v", created, err)
	}
	git(directory, "branch", "-m", "fix/intermediate")
	git(directory, "branch", "-m", "fix/task")
	git(directory, "commit", "--allow-empty", "-m", "progress")
	proof := filepath.Join(directory, "unfinished.txt")
	if err = os.WriteFile(proof, []byte("keep this work"), 0600); err != nil {
		t.Fatal(err)
	}
	for range 2 {
		reused, err := s.reuseWorkspace(ctx, spec)
		if err != nil || reused.Branch != "fix/task" || reused.ID != workspace.ID || reused.StartOID != workspace.StartOID {
			t.Fatalf("renamed workspace: %+v %v", reused, err)
		}
	}
	if body, err := os.ReadFile(proof); err != nil || string(body) != "keep this work" {
		t.Fatalf("lost work: %s %v", body, err)
	}
	git(directory, "switch", "--ignore-other-worktrees", "main")
	if _, err = s.reuseWorkspace(ctx, spec); err == nil || err.Error() != "WORKSPACE_STALE" {
		t.Fatalf("checkout switch accepted: %v", err)
	}
	git(directory, "branch", "-D", "fix/task")
	if _, err = s.reuseWorkspace(ctx, spec); err == nil || err.Error() != "WORKSPACE_STALE" {
		t.Fatalf("checkout switch with deleted old branch accepted: %v", err)
	}
	if err = os.RemoveAll(directory); err != nil {
		t.Fatal(err)
	}
	if _, err = s.reuseWorkspace(ctx, spec); err == nil || err.Error() != "WORKSPACE_STALE" {
		t.Fatalf("missing workspace accepted: %v", err)
	}
	if err = os.MkdirAll(directory, 0700); err != nil {
		t.Fatal(err)
	}
	git(directory, "init", "-b", "fix/task")
	if _, err = s.reuseWorkspace(ctx, spec); err == nil || err.Error() != "WORKSPACE_STALE" {
		t.Fatalf("replacement repo accepted: %v", err)
	}
}

func TestNativeWorkspacePreparationReturnsStructuredError(t *testing.T) {
	s := testService(t)
	var output bytes.Buffer
	err := s.HoldNative(context.Background(), Spec{Key: "missing-workspace", Executor: "native", ProjectID: "missing"}, json.NewDecoder(strings.NewReader("")), &output)
	var frame map[string]string
	if err == nil || json.Unmarshal(output.Bytes(), &frame) != nil || frame["errorCode"] != "UNKNOWN_PROJECT" || frame["state"] != "failed" {
		t.Fatalf("lost preparation error: %s %v", output.String(), err)
	}
}

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
