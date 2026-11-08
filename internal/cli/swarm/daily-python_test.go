package swarm

import (
	"crypto/sha256"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/agentruntime"
	metadb "github.com/ybz21/Roami/internal/storage"
)

func TestDailyThroughRealPythonAndGoCLI(t *testing.T) {
	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv required")
	}
	repository, err := filepath.Abs("../../..")
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	paths, err := metadb.ResolvePaths(root, root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = paths.Ensure(); err != nil {
		t.Fatal(err)
	}
	agent, err := agentruntime.Resolve(root, root)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.MkdirAll(filepath.Dir(agent.Socket), 0700); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Remove(agent.Socket) })
	for _, name := range []string{"tests/swarm_daily_scenario.py", "src/roami_agent/storage/swarm_daily_goal.py", "src/roami_agent/server/swarm_routes.py"} {
		body, err := os.ReadFile(filepath.Join(repository, "agent-runtime", name))
		if err != nil {
			t.Fatal(err)
		}
		t.Logf("actual runtime source %s %x", name, sha256.Sum256(body))
	}
	binary := filepath.Join(t.TempDir(), "roami")
	build := exec.Command("go", "build", "-o", binary, "./cmd/roami")
	build.Dir = repository
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v %s", err, output)
	}
	command := exec.Command("uv", "run", "--frozen", "--directory", filepath.Join(repository, "agent-runtime"), "python", "tests/swarm_daily_scenario.py", binary, root, root, agent.Socket)
	command.Env = append(os.Environ(), "ROAMI_HOME="+root, "ROAMI_DATA="+root, "ROAMI_DATABASE_DIR="+paths.Database, "ROAMI_BACKUP_DIR="+paths.Backup, "ROAMI_CONFIG="+filepath.Join(root, "config.yaml"))
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("daily goal integration: %v\n%s", err, output)
	}
	if !strings.Contains(string(output), "daily original Main through real Go CLI and Python Unix HTTP passed") {
		t.Fatalf("missing end-to-end receipt: %s", output)
	}
}
