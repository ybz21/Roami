package env

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestPushPreviewAndReceipt(t *testing.T) {
	for _, scenario := range []string{"preview", "partial", "empty-env", "empty-sessions"} {
		t.Run(scenario, func(t *testing.T) {
			root := t.TempDir()
			tmux := filepath.Join(root, "tmux")
			script := "#!/bin/sh\nif [ \"$1\" = list-sessions ]; then\n"
			if scenario != "empty-sessions" {
				script += "printf 'one\\ntwo\\n'\n"
			}
			script += "exit 0\nfi\nprintf '%s\\n' called >> '" + filepath.Join(root, "writes") + "'\n[ \"$3\" != '=two' ]\n"
			if err := os.WriteFile(tmux, []byte(script), 0700); err != nil {
				t.Fatal(err)
			}
			rt := runtime.Runtime{TmuxBin: tmux, EnvFile: filepath.Join(root, "env")}
			if scenario != "empty-env" {
				if err := os.WriteFile(rt.EnvFile, []byte("PRIVATE_VALUE=do-not-expose\n"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			var output bytes.Buffer
			if err := PushJSON(rt, &output, scenario == "preview"); err != nil {
				t.Fatal(err)
			}
			var result pushResult
			if err := json.Unmarshal(output.Bytes(), &result); err != nil {
				t.Fatal(err)
			}
			if strings.Contains(output.String(), "do-not-expose") {
				t.Fatal("receipt leaked a value")
			}
			switch scenario {
			case "partial":
				if result.Success != 1 || result.Failed != 1 || result.Skipped != 0 {
					t.Fatalf("untruthful receipt: %+v", result)
				}
			case "empty-env":
				if result.Skipped != 2 || len(result.Keys) != 0 {
					t.Fatalf("empty variables: %+v", result)
				}
			case "empty-sessions":
				if len(result.Sessions) != 0 || result.Success != 0 {
					t.Fatalf("empty sessions: %+v", result)
				}
			case "preview":
				if len(result.Sessions) != 2 || len(result.Keys) != 1 || result.Keys[0] != "PRIVATE_VALUE" {
					t.Fatalf("preview: %+v", result)
				}
			}
			if scenario != "partial" {
				if _, err := os.Stat(filepath.Join(root, "writes")); !os.IsNotExist(err) {
					t.Fatal("preview or empty push mutated a session")
				}
			}
		})
	}
}
