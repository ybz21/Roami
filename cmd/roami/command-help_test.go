package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestIndexedSubcommandHelpDoesNotInitializeResources(t *testing.T) {
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	for _, command := range []string{
		"session ls", "session capture", "session fork", "session rename", "session resolve", "session send",
		"chrome tabs", "chrome goto", "chrome screenshot", "chrome click", "chrome fill", "chrome eval", "chrome record", "chrome record start", "chrome record stop", "swarm status",
		"project ls", "project show", "agent capability list", "agent capability show",
	} {
		t.Run(command, func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "uninitialized")
			args := append(strings.Fields(command), "--help")
			raw, _ := json.Marshal(args)
			cmd := exec.Command(executable, "-test.run=^TestSwarmCLIChild$")
			cmd.Env = append(os.Environ(), "ROAMI_SWARM_CLI_TEST_ARGS="+string(raw), "ROAMI_HOME="+root, "ROAMI_DATA="+root, "ROAMI_DATABASE_DIR="+filepath.Join(root, "database"), "ROAMI_BACKUP_DIR="+filepath.Join(root, "backups"), "ROAMI_CONFIG="+filepath.Join(root, "missing.yaml"), "ROAMI_SERVER=http://127.0.0.1:1", "TMUX_BIN="+filepath.Join(root, "unavailable-tmux"))
			output, err := cmd.CombinedOutput()
			if err != nil || len(output) == 0 {
				t.Fatalf("%v: %v %s", args, err, output)
			}
			if _, err = os.Stat(root); !os.IsNotExist(err) {
				t.Fatalf("help initialized resources: %v", args)
			}
		})
	}
}
