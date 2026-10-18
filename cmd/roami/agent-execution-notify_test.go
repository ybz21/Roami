package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestOriginalNotifierAndLifecycleFailIndependently(t *testing.T) {
	for _, scenario := range []string{"success", "original-fails", "storage-fails"} {
		t.Run(scenario, func(t *testing.T) {
			root := t.TempDir()
			for key, value := range map[string]string{"ROAMI_HOME": root, "ROAMI_DATA": root, "ROAMI_DATABASE_DIR": filepath.Join(root, "database"), "ROAMI_BACKUP_DIR": filepath.Join(root, "backups"), "ROAMI_CONFIG": filepath.Join(root, "config.yaml"), "TMUX_PANE": "%fixture"} {
				t.Setenv(key, value)
			}
			notifier := filepath.Join(root, "notifier")
			script := "#!/bin/sh\nprintf '%s' \"$1\" > '" + filepath.Join(root, "notified") + "'\n"
			if scenario == "original-fails" {
				script += "exit 1\n"
			}
			if err := os.WriteFile(notifier, []byte(script), 0700); err != nil {
				t.Fatal(err)
			}
			data, _ := json.Marshal([]string{notifier})
			digest := sha256.Sum256(data)
			directory := filepath.Join(root, "agents", "codex-notifiers")
			if err := os.MkdirAll(directory, 0700); err != nil {
				t.Fatal(err)
			}
			chain := filepath.Join(directory, hex.EncodeToString(digest[:])+".json")
			if err := os.WriteFile(chain, data, 0600); err != nil {
				t.Fatal(err)
			}
			tmux := filepath.Join(root, "tmux")
			identity := fmt.Sprintf("2026-1017-0900-0001\t$1\t1792200000\tfixture-server\t%%fixture\t%d\t%s\n", os.Getpid(), root)
			if err := os.WriteFile(tmux, []byte("#!/bin/sh\ncat <<'IDENTITY'\n"+identity+"IDENTITY\n"), 0700); err != nil {
				t.Fatal(err)
			}
			if scenario == "storage-fails" {
				if err := os.WriteFile(filepath.Join(root, "database"), []byte("fixture blocker"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			notification := `{"hook_event_name":"SessionStart","session_id":"fixture-provider"}`
			code := runAgentExecution([]string{"notify", "--executor", "codex", "--chain", chain, "--notification", notification, "--tmux-bin", tmux})
			if (code == 0) != (scenario == "success") {
				t.Fatalf("unexpected status %d", code)
			}
			received, err := os.ReadFile(filepath.Join(root, "notified"))
			if err != nil || string(received) != notification {
				t.Fatal("original notifier lost its event")
			}
			states, err := filepath.Glob(filepath.Join(root, "agents", "session-lifecycle", "*", "state.json"))
			if err != nil {
				t.Fatal(err)
			}
			if scenario != "storage-fails" && len(states) != 1 {
				t.Fatal("original notifier failure suppressed lifecycle observation")
			}
		})
	}
}
