package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestSwarmCLIChild(t *testing.T) {
	raw := os.Getenv("ROAMI_SWARM_CLI_TEST_ARGS")
	if raw == "" {
		t.Skip("subprocess fixture")
	}
	var args []string
	if err := json.Unmarshal([]byte(raw), &args); err != nil {
		t.Fatal(err)
	}
	handled, code := runCLI(args, "")
	if !handled {
		t.Fatal("swarm entry not handled")
	}
	os.Exit(code)
}
func TestSwarmRootAndSessionHelpAreReadOnly(t *testing.T) {
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{{"swarm", "help"}, {"help", "swarm"}, {"swarm", "pause", "sw-0123456789abcdef0123456789abcdef", "--help"}, {"session", "swarm", "member", "add", "--help"}} {
		root := filepath.Join(t.TempDir(), "uninitialized")
		raw, _ := json.Marshal(args)
		cmd := exec.Command(executable, "-test.run=^TestSwarmCLIChild$")
		cmd.Env = append(os.Environ(), "ROAMI_SWARM_CLI_TEST_ARGS="+string(raw), "ROAMI_HOME="+root, "ROAMI_DATA="+root, "ROAMI_DATABASE_DIR="+filepath.Join(root, "database"), "ROAMI_BACKUP_DIR="+filepath.Join(root, "backups"), "TMUX_BIN="+filepath.Join(root, "unavailable-tmux"))
		output, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("%v: %v %s", args, err, output)
		}
		if !strings.Contains(string(output), "roami swarm") || !strings.Contains(string(output), "\n用法\n") {
			t.Fatalf("incomplete help: %s", output)
		}
		if _, err = os.Stat(root); !os.IsNotExist(err) {
			t.Fatalf("help initialized storage: %v", args)
		}
	}
}
