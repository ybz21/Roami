package agentlifecycle

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

func claudeHooks(command string) map[string]any {
	hooks := map[string]any{}
	for _, event := range []string{"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "SubagentStart", "SubagentStop", "Stop", "StopFailure", "SessionEnd", "Notification"} {
		group := map[string]any{"hooks": []any{map[string]any{"type": "command", "command": command, "timeout": 5}}}
		if event == "Notification" {
			group["matcher"] = "^idle_prompt$"
		}
		hooks[event] = []any{group}
	}
	return map[string]any{"hooks": hooks}
}

// PrepareClaude scopes callbacks and an optional classifier model to one invocation.
func PrepareClaude(ctx context.Context, options SessionOptions) ([]string, error) {
	for _, path := range []string{options.Executable, options.Directory, options.DataDir} {
		if !filepath.IsAbs(path) {
			return nil, fmt.Errorf("INVALID_CLAUDE_LIFECYCLE_PATH")
		}
	}
	for _, path := range []string{options.HomeDir, options.DatabaseDir, options.BackupDir} {
		if path != "" && !filepath.IsAbs(path) {
			return nil, fmt.Errorf("INVALID_CLAUDE_LIFECYCLE_PATH")
		}
	}
	probeContext, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	command := exec.CommandContext(probeContext, options.Binary, "--help")
	command.Dir = options.Directory
	output := &boundedOutput{limit: 256_000}
	command.Stdout, command.Stderr, command.WaitDelay = output, io.Discard, time.Second
	if command.Run() != nil || !bytes.Contains(output.data, []byte("--settings")) {
		return nil, fmt.Errorf("CLAUDE_LIFECYCLE_UNAVAILABLE")
	}
	args := append(callbackArguments(options, "claude", "event"), "--file", "-")
	quoted := make([]string, len(args))
	for index, arg := range args {
		quoted[index] = shellQuote(arg)
	}
	config := claudeHooks(strings.Join(quoted, " "))
	if options.ClaudeClassifierModel != "" {
		config["env"] = map[string]string{
			"CLAUDE_CODE_AUTO_MODE_MODEL":  options.ClaudeClassifierModel,
			"CLAUDE_CODE_AUTO_MODE_SERVER": "0",
		}
	}
	settings, err := json.Marshal(config)
	if err != nil {
		return nil, fmt.Errorf("CLAUDE_LIFECYCLE_UNAVAILABLE")
	}
	return []string{"--settings", string(settings)}, nil
}
