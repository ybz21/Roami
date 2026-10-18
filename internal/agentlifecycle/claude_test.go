package agentlifecycle

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestClaudeScopesObserverHooksWithoutPolicyOrPermissionChanges(t *testing.T) {
	options := fixtureOptions(t, map[string]any{})
	args, err := PrepareClaude(context.Background(), options)
	if err != nil || len(args) != 2 || args[0] != "--settings" {
		t.Fatalf("claude arguments: %v %v", args, err)
	}
	var config map[string]map[string][]map[string]any
	if err := json.Unmarshal([]byte(args[1]), &config); err != nil {
		t.Fatal(err)
	}
	if len(config) != 1 || len(config["hooks"]) != 11 {
		t.Fatal("observer configuration changes unrelated settings")
	}
	for event, groups := range config["hooks"] {
		if len(groups) != 1 {
			t.Fatal("invalid group")
		}
		if event == "Notification" && groups[0]["matcher"] != "^idle_prompt$" {
			t.Fatal("completion must only use idle notifications")
		}
		hook := groups[0]["hooks"].([]any)[0].(map[string]any)
		command := hook["command"].(string)
		if !strings.Contains(command, "'--executor' 'claude'") || !strings.Contains(command, "'--data-dir' '"+options.DataDir+"'") || strings.Contains(command, "bypass") {
			t.Fatal("invalid observer command")
		}
	}
	manual, err := HookConfiguration(options.Executable, "claude")
	if err != nil || manual["notify"] != nil {
		t.Fatal("Claude uses notification hooks, not the Codex notifier")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if args, err := PrepareClaude(ctx, options); err == nil || len(args) != 0 {
		t.Fatal("cancelled preparation returned hooks")
	}
}

func TestInstalledClaudeReadOnlyHelpContract(t *testing.T) {
	if os.Getenv("ROAMI_TEST_INSTALLED_CLAUDE") != "1" {
		t.Skip("explicit opt-in for installed Claude help inspection")
	}
	binary, err := exec.LookPath("claude")
	if err != nil {
		t.Fatal(err)
	}
	executable, _ := os.Executable()
	args, err := PrepareClaude(context.Background(), SessionOptions{Binary: binary, Executable: executable, Directory: t.TempDir(), DataDir: filepath.Join(t.TempDir(), "data")})
	if err != nil || len(args) != 2 {
		t.Fatalf("installed Claude rejected help contract: %v", err)
	}
}
