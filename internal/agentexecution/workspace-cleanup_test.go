package agentexecution

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/backend/project"
	"github.com/ybz21/Roami/internal/gitcontext"
)

func TestWorkspaceCleanupPreservesUncommittedChangesAndRetries(t *testing.T) {
	s := testService(t)
	ctx := context.Background()
	repo := t.TempDir()
	git := func(directory string, args ...string) string {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", directory}, args...)...)
		cmd.Env = append(gitcontext.ForDirectory(os.Environ()), "GIT_AUTHOR_NAME=Fixture", "GIT_AUTHOR_EMAIL=fixture@example.invalid", "GIT_COMMITTER_NAME=Fixture", "GIT_COMMITTER_EMAIL=fixture@example.invalid")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	git(repo, "init", "-b", "main")
	git(repo, "commit", "--allow-empty", "-m", "initial")
	db, err := s.platform(ctx)
	if err != nil {
		t.Fatal(err)
	}
	projectID, _ := project.NewStore(s.Runtime.DataDir, db).Add(repo, "cleanup")
	spec := Spec{Key: "cleanup", ProjectID: projectID, Executor: "native"}
	dir, _ := s.directory(spec.Key)
	if err = os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	workspace, err := s.prepareWorkspace(ctx, spec, filepath.Base(dir))
	if err != nil {
		t.Fatal(err)
	}
	for name, value := range map[string]any{"spec.json": spec, "receipt.json": Receipt{State: "native_running", Workspace: &workspace}} {
		if err = writeJSON(filepath.Join(dir, name), value); err != nil {
			t.Fatal(err)
		}
	}
	if _, err = s.CleanupWorkspace(ctx, spec.Key); err == nil || err.Error() != "WORKSPACE_OUTCOME_UNKNOWN" {
		t.Fatalf("missing stop proof: %v", err)
	}
	if err = writeJSON(filepath.Join(dir, "result.json"), Result{State: "succeeded", Summary: "NATIVE_TOOLS_STOPPED"}); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(workspace.Directory, "deliverable.txt")
	if err = os.WriteFile(file, []byte("preserve output"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = s.CleanupWorkspace(ctx, spec.Key); err == nil || err.Error() != "WORKTREE_DIRTY" {
		t.Fatalf("dirty cleanup: %v", err)
	}
	if body, err := os.ReadFile(file); err != nil || string(body) != "preserve output" {
		t.Fatalf("lost output: %s %v", body, err)
	}
	git(workspace.Directory, "add", "deliverable.txt")
	git(workspace.Directory, "commit", "-m", "completed output")
	git(workspace.Directory, "branch", "-m", "feat/cleanup-output")
	for range 2 {
		result, err := s.CleanupWorkspace(ctx, spec.Key)
		if err != nil || result["state"] != "cleaned" {
			t.Fatalf("cleanup: %v %v", result, err)
		}
	}
	if _, err = os.Stat(workspace.Directory); !os.IsNotExist(err) {
		t.Fatalf("worktree remains: %v", err)
	}
	if got := git(repo, "show", "feat/cleanup-output:deliverable.txt"); got != "preserve output" {
		t.Fatalf("unmerged branch lost: %s", got)
	}
	if strings.Contains(git(repo, "worktree", "list", "--porcelain"), workspace.Directory) {
		t.Fatal("worktree registration remains")
	}
	spec.Key = "unused-workspace"
	dir, _ = s.directory(spec.Key)
	if err = os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	unused, err := s.prepareWorkspace(ctx, spec, filepath.Base(dir))
	if err != nil {
		t.Fatal(err)
	}
	for name, value := range map[string]any{"spec.json": spec, "receipt.json": Receipt{State: "native_running", Workspace: &unused}, "result.json": Result{State: "succeeded", Summary: "NATIVE_TOOLS_STOPPED"}} {
		if err = writeJSON(filepath.Join(dir, name), value); err != nil {
			t.Fatal(err)
		}
	}
	if _, err = s.CleanupWorkspace(ctx, spec.Key); err != nil {
		t.Fatal(err)
	}
	if got := git(repo, "branch", "--list", unused.Branch); got != "" {
		t.Fatalf("unused task branch remains: %s", got)
	}
	spec.Key, spec.Executor = "professional-workspace", "codex"
	dir, _ = s.directory(spec.Key)
	if err = os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	professional, err := s.prepareWorkspace(ctx, spec, filepath.Base(dir))
	if err != nil {
		t.Fatal(err)
	}
	binding := SessionBinding{ID: "original-session", Name: "original-session", TmuxID: "$1", Created: "1", Server: "test-server", Pane: "%1", ProviderID: "original-provider"}
	receipt := Receipt{Session: binding.ID, Workspace: &professional, Binding: &binding}
	for name, value := range map[string]any{"spec.json": spec, "receipt.json": receipt} {
		if err = writeJSON(filepath.Join(dir, name), value); err != nil {
			t.Fatal(err)
		}
	}
	if _, err = s.CleanupWorkspace(ctx, spec.Key); err == nil || err.Error() != "SESSION_NOT_IDLE" {
		t.Fatalf("missing professional closure proof: %v", err)
	}
	proof := filepath.Join(s.Runtime.DataDir, "agents", "closed-sessions", binding.resourceID()+".json")
	if err = os.MkdirAll(filepath.Dir(proof), 0700); err != nil {
		t.Fatal(err)
	}
	closed := Status{Receipt: receipt}
	closed.State = "closed"
	if err = writeJSON(proof, closed); err != nil {
		t.Fatal(err)
	}
	if _, err = s.CleanupWorkspace(ctx, spec.Key); err != nil {
		t.Fatal(err)
	}
	if _, err = os.Stat(professional.Directory); !os.IsNotExist(err) {
		t.Fatalf("professional worktree remains: %v", err)
	}
}

func TestWorkspaceCleanupNeverRemovesAnExplicitDirectory(t *testing.T) {
	s := testService(t)
	spec := Spec{Key: "explicit", Executor: "native", Directory: t.TempDir()}
	dir, _ := s.directory(spec.Key)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	for name, value := range map[string]any{"spec.json": spec, "receipt.json": Receipt{Workspace: &Workspace{Directory: spec.Directory}}} {
		if err := writeJSON(filepath.Join(dir, name), value); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := s.CleanupWorkspace(context.Background(), spec.Key); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(spec.Directory); err != nil {
		t.Fatalf("explicit directory removed: %v", err)
	}
}
