package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestNativeSessionModelOptions(t *testing.T) {
	options, err := parseNativeSessionOptions([]string{"Review", "--kind", "roami", "--task", "read files", "-model", "free-pool", "--free-only", "--json", "--key", "stable"})
	if err != nil || options.Model != "free-pool" || !options.FreeOnly || options.Task != "read files" || options.Key != "stable" {
		t.Fatalf("lost selection: %+v %v", options, err)
	}
	for _, args := range [][]string{{"--kind", "roami"}, {"--kind", "codex", "--task", "test"}, {"--model"}, {"--kind", "roami", "--task", "test", "--size", "80x24"}} {
		if _, err := parseNativeSessionOptions(args); err == nil {
			t.Fatal("invalid options accepted", args)
		}
	}
}
func TestNativeSessionDispatchLeavesShellAndHelpUntouched(t *testing.T) {
	for _, command := range []string{"new label --kind roami --model free-pool --task test", "new --kind=roami --task=test"} {
		if !nativeSessionNewRequested(strings.Fields(command)) {
			t.Fatal(command)
		}
	}
	for _, command := range []string{"new label --dir .", "new --kind roami --help", "fork parent name", "new --task text"} {
		if nativeSessionNewRequested(strings.Fields(command)) {
			t.Fatal(command)
		}
	}
}

func TestManagedNativeSessionCreationUsesRegisteredAdmission(t *testing.T) {
	for _, name := range []string{"ROAMI_AGENT_CALLER_ROLE", "ROAMI_AGENT_TURN_ID", "ROAMI_AGENT_TOOL_CALL_ID"} {
		t.Run(name, func(t *testing.T) {
			for _, key := range []string{"ROAMI_AGENT_CALLER_ROLE", "ROAMI_AGENT_TURN_ID", "ROAMI_AGENT_TOOL_CALL_ID"} {
				t.Setenv(key, "")
			}
			t.Setenv(name, "managed-context")
			root := filepath.Join(t.TempDir(), "not-created")
			t.Setenv("ROAMI_HOME", root)
			if code := runNativeSessionNew([]string{"--kind", "roami", "--task", "Review fixture"}); code != 1 {
				t.Fatal("managed caller bypassed registered admission", code)
			}
			if _, err := os.Stat(root); !os.IsNotExist(err) {
				t.Fatal("managed call initialized resources", err)
			}
		})
	}
}
