package agentexecution

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/ybz21/Roami/backend/project"
	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestProjectLaunchUsesFreshGoWorkspaceAndNeverRepreparesOnRetry(t *testing.T) {
	// Git hooks export repository bindings; fixtures must not inherit any of them.
	for _, entry := range os.Environ() {
		name, _, _ := strings.Cut(entry, "=")
		if strings.HasPrefix(name, "GIT_") {
			t.Setenv(name, "")
			if err := os.Unsetenv(name); err != nil {
				t.Fatal(err)
			}
		}
	}
	t.Setenv("GIT_CONFIG_GLOBAL", os.DevNull)
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")

	tmux, err := exec.LookPath("tmux")
	if err != nil {
		t.Skip("tmux required for project execution integration")
	}
	root := t.TempDir()
	t.Setenv("ROAMI_HOME", filepath.Join(root, "instance"))
	t.Setenv("ROAMI_DATA", filepath.Join(root, "instance"))
	t.Setenv("GIT_AUTHOR_NAME", "Executor fixture")
	t.Setenv("GIT_AUTHOR_EMAIL", "executor@example.invalid")
	t.Setenv("GIT_COMMITTER_NAME", "Executor fixture")
	t.Setenv("GIT_COMMITTER_EMAIL", "executor@example.invalid")
	command := func(dir, bin string, args ...string) string {
		t.Helper()
		cmd := exec.Command(bin, args...)
		cmd.Dir = dir
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("%s %v: %v\n%s", bin, args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	git := func(dir string, args ...string) string {
		t.Helper()
		return command(root, "git", append([]string{"-C", dir}, args...)...)
	}
	repo := filepath.Join(root, "project with spaces")
	command(root, "git", "init", "-b", "main", repo)
	if err = os.WriteFile(filepath.Join(repo, "base.txt"), []byte("base"), 0600); err != nil {
		t.Fatal(err)
	}
	git(repo, "add", "base.txt")
	git(repo, "commit", "-m", "initial")
	old := git(repo, "rev-parse", "HEAD")
	remote := filepath.Join(root, "remote.git")
	git(repo, "clone", "--bare", repo, remote)
	git(repo, "remote", "add", "origin", remote)
	source := filepath.Join(root, "source")
	git(repo, "clone", remote, source)
	if err = os.WriteFile(filepath.Join(source, "remote.txt"), []byte("remote advance"), 0600); err != nil {
		t.Fatal(err)
	}
	git(source, "add", "remote.txt")
	git(source, "commit", "-m", "remote advance")
	git(source, "push", "origin", "main")
	fresh := git(source, "rev-parse", "HEAD")
	binary := filepath.Join(root, "roami")
	repository, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	command(repository, "go", "build", "-o", binary, "./cmd/roami")
	binDir := filepath.Join(root, "bin")
	if err = os.MkdirAll(binDir, 0700); err != nil {
		t.Fatal(err)
	}
	calls := filepath.Join(root, "agent-calls")
	fake := "#!/bin/sh\ncat >/dev/null\nprintf 'called\\n' >> " + quote(calls) + "\npwd\ngit rev-parse HEAD\nprintf 'execution' > execution-proof.txt\n"
	if err = os.WriteFile(filepath.Join(binDir, "codex"), []byte(fake), 0700); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(binDir, "ttmux"), []byte("#!/bin/sh\necho 'legacy ttmux must not be invoked' >&2\nexit 99\n"), 0700); err != nil {
		t.Fatal(err)
	}
	socket := fmt.Sprintf("roami-project-%d-%d", os.Getpid(), time.Now().UnixNano())
	wrapper := filepath.Join(binDir, "tmux")
	if err = os.WriteFile(wrapper, []byte("#!/bin/sh\nexec "+quote(tmux)+" -L "+quote(socket)+" \"$@\"\n"), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("TMUX_BIN", wrapper)
	t.Setenv("PATH", binDir+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Cleanup(func() { _ = exec.Command(wrapper, "kill-server").Run() })
	s := Service{Runtime: runtime.New(), Executable: binary}
	db, err := s.platform(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	store := project.NewStore(s.Runtime.DataDir, db)
	projectID, _ := store.Add(repo, "Project fixture")
	store.SetPrefs(projectID, func(p *project.Prefs) { p.DefaultBase = "main" })
	spec := Spec{Key: "project-run", Executor: "codex", ProjectID: projectID, Prompt: "write proof", TimeoutSeconds: 30}
	status, err := s.Launch(context.Background(), spec)
	if err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(15 * time.Second)
	for status.Result == nil && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
		status, err = s.Status(spec.Key)
		if err != nil {
			t.Fatal(err)
		}
	}
	if status.Result == nil || status.Result.State != "succeeded" || status.Workspace == nil {
		t.Fatalf("project execution did not complete: %+v", status)
	}
	workspace := *status.Workspace
	if workspace.StartOID != fresh || workspace.ProjectID != projectID || workspace.Base != "main" || workspace.Directory == repo {
		t.Fatalf("wrong preparation receipt: %+v", workspace)
	}
	if !strings.Contains(status.Result.Summary, workspace.Directory) || !strings.Contains(status.Result.Summary, fresh) {
		t.Fatalf("runner ignored workspace: %+v", status.Result)
	}
	if git(repo, "rev-parse", "main") != old {
		t.Fatal("local main was moved during preparation")
	}
	if _, err = os.Stat(filepath.Join(repo, "execution-proof.txt")); !os.IsNotExist(err) {
		t.Fatal("coding task wrote into main checkout")
	}
	if _, err = os.Stat(filepath.Join(workspace.Directory, "execution-proof.txt")); err != nil {
		t.Fatal("coding task did not run in prepared checkout")
	}
	before := git(repo, "worktree", "list", "--porcelain")
	replay, err := s.Launch(context.Background(), spec)
	if err != nil {
		t.Fatal(err)
	}
	if replay.Workspace == nil || *replay.Workspace != workspace || git(repo, "worktree", "list", "--porcelain") != before {
		t.Fatal("retry prepared another workspace")
	}
	git(repo, "remote", "set-url", "origin", filepath.Join(root, "absent.git"))
	failed, err := s.Launch(context.Background(), Spec{Key: "failed-fetch", Executor: "codex", ProjectID: projectID, Prompt: "must not start", TimeoutSeconds: 30})
	if err != nil {
		t.Fatal(err)
	}
	if failed.Result == nil || failed.Result.State != "failed" || failed.Result.Summary != "FETCH_FAILED" {
		t.Fatalf("fetch failure was not propagated: %+v", failed)
	}
	if git(repo, "worktree", "list", "--porcelain") != before {
		t.Fatal("failed fetch created a stale workspace")
	}
	count, err := os.ReadFile(calls)
	if err != nil {
		t.Fatal(err)
	}
	if string(count) != "called\n" {
		t.Fatalf("coding agent launched more than once: %s", count)
	}
}

func TestDirectoryProjectKeepsItsIdentityAndUnknownProjectDoesNotFallBack(t *testing.T) {
	s := testService(t)
	db, err := s.platform(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	store := project.NewStore(s.Runtime.DataDir, db)
	id, _ := store.Add(directory, "Directory project")
	workspace, err := s.prepareWorkspace(context.Background(), Spec{ProjectID: id}, strings.Repeat("a", 64))
	if err != nil || workspace.ProjectID != id || workspace.Directory != directory || workspace.Branch != "" {
		t.Fatalf("directory project: %+v, %v", workspace, err)
	}
	_, err = s.prepareWorkspace(context.Background(), Spec{ProjectID: "unknown", Directory: directory}, strings.Repeat("b", 64))
	if err == nil || err.Error() != "UNKNOWN_PROJECT" {
		t.Fatalf("unknown project fell back to caller's directory: %v", err)
	}
	_, err = s.Launch(context.Background(), Spec{Key: "override", Executor: "codex", ProjectID: id, Directory: directory, Prompt: "work", TimeoutSeconds: 10})
	if err == nil || err.Error() != "INVALID_EXECUTION_SPEC" {
		t.Fatalf("mixed project/directory target accepted: %v", err)
	}
}
