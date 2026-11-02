package agentexecution

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/memguard"
)

func TestPersistentSessionsRetainContextUntilExplicitClosure(t *testing.T) {
	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv required")
	}
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("tmux required")
	}
	if _, _, err := memguard.ScopeProcesses(os.Getpid()); err != nil {
		t.Skip("process proof requires a pane scope")
	}
	repository, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	recordRuntimeSources(t, repository, "persistent_session_scenario.py")
	if _, err := os.ReadFile(filepath.Join(repository, "agent-runtime", "tests", "persistent_provider.py")); err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	binary := filepath.Join(root, "roami")
	build := exec.Command("go", "build", "-o", binary, "./cmd/roami")
	build.Dir = repository
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v %s", err, output)
	}
	instance := filepath.Join(root, "instance")
	launcher := filepath.Join(repository, "scripts/dev/isolated-roami.sh")
	t.Cleanup(func() {
		if output, err := exec.Command(launcher, instance, "--stop").CombinedOutput(); err != nil {
			t.Logf("isolated cleanup: %v %s", err, output)
		}
	})
	command := exec.Command(launcher, instance, "uv", "run", "--frozen", "--directory", filepath.Join(repository, "agent-runtime"), "python", "tests/persistent_session_scenario.py", binary, instance)
	command.Dir = repository
	if output, err := command.CombinedOutput(); err != nil || !strings.Contains(string(output), "persistent session scenario passed") {
		t.Fatalf("persistent context: %v\n%s", err, output)
	}
}
