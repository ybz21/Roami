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

type SessionOptions struct {
	Binary      string
	Executable  string
	Directory   string
	DataDir     string
	HomeDir     string
	DatabaseDir string
	BackupDir   string
	TmuxBin     string
}

type codexConfiguration struct {
	Notify           []string `json:"notify"`
	ManagedHooksOnly bool     `json:"allow_managed_hooks_only"`
	Features         struct {
		Hooks *bool `json:"hooks"`
	} `json:"features"`
}

func HookConfiguration(executable, executor string) (map[string]any, error) {
	if executor == "claude" {
		return claudeHooks(shellQuote(executable) + " agent execution event --executor claude --file -"), nil
	}
	if executor != "codex" {
		return nil, fmt.Errorf("SESSION_COMPLETION_ADAPTER_UNAVAILABLE")
	}
	command := shellQuote(executable) + " agent execution event --executor codex --file -"
	hooks := map[string]any{}
	for _, event := range []string{"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart", "Interrupt", "SessionEnd"} {
		timeout := 5
		if event == "Interrupt" || event == "SessionEnd" {
			timeout = 3
		}
		hooks[event] = []any{map[string]any{"hooks": []any{map[string]any{"type": "command", "command": command, "timeout": timeout}}}}
	}
	return map[string]any{"hooks": hooks, "notify": []string{executable, "agent", "execution", "event", "--executor", "codex", "--notification"}}, nil
}

// PrepareCodex scopes callbacks to one invocation and preserves the effective notifier.
func PrepareCodex(ctx context.Context, options SessionOptions) ([]string, error) {
	if !filepath.IsAbs(options.Executable) || !filepath.IsAbs(options.Directory) || !filepath.IsAbs(options.DataDir) {
		return nil, fmt.Errorf("INVALID_CODEX_LIFECYCLE_PATH")
	}
	for _, path := range []string{options.HomeDir, options.DatabaseDir, options.BackupDir} {
		if path != "" && !filepath.IsAbs(path) {
			return nil, fmt.Errorf("INVALID_CODEX_LIFECYCLE_PATH")
		}
	}
	probeContext, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	help := exec.CommandContext(probeContext, options.Binary, "--help")
	help.Stdout = &boundedOutput{limit: 256_000}
	help.Stderr = io.Discard
	help.WaitDelay = time.Second
	if help.Run() != nil || !bytes.Contains(help.Stdout.(*boundedOutput).data, []byte("--no-daemon")) {
		return nil, fmt.Errorf("CODEX_LOCAL_LIFECYCLE_UNAVAILABLE")
	}
	config, err := readCodexConfiguration(probeContext, options.Binary, options.Directory)
	if err != nil {
		return nil, err
	}
	if config.ManagedHooksOnly || (config.Features.Hooks != nil && !*config.Features.Hooks) {
		return nil, fmt.Errorf("CODEX_LIFECYCLE_DISABLED")
	}

	hookArgs := append(callbackArguments(options, "codex", "event"), "--file", "-")
	quotedHook := make([]string, len(hookArgs))
	for index, arg := range hookArgs {
		quotedHook[index] = shellQuote(arg)
	}
	args := []string{"--no-daemon"}
	for _, event := range []string{"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart", "Interrupt", "SessionEnd"} {
		timeout := 5
		if event == "Interrupt" || event == "SessionEnd" {
			timeout = 3
		}
		command, _ := json.Marshal(strings.Join(quotedHook, " "))
		value := fmt.Sprintf("hooks.%s=[{hooks=[{type=\"command\",command=%s,timeout=%d}]}]", event, command, timeout)
		args = append(args, "-c", value)
	}
	notify := append(callbackArguments(options, "codex", "event"), "--notification")
	if len(config.Notify) != 0 {
		path, err := storeNotifier(options.DataDir, config.Notify)
		if err != nil {
			return nil, err
		}
		notify = append(callbackArguments(options, "codex", "notify"), "--chain", path, "--notification")
	}
	value, _ := json.Marshal(notify)
	return append(args, "-c", "notify="+string(value)), nil
}

type boundedOutput struct {
	data  []byte
	limit int
}

func (output *boundedOutput) Write(data []byte) (int, error) {
	if len(output.data)+len(data) > output.limit {
		return 0, io.ErrShortWrite
	}
	output.data = append(output.data, data...)
	return len(data), nil
}

func readCodexConfiguration(ctx context.Context, binary, directory string, overrides ...string) (codexConfiguration, error) {
	var config codexConfiguration
	command := exec.CommandContext(ctx, binary, append(overrides, "app-server", "--stdio")...)
	command.Dir = directory
	command.Stderr = io.Discard
	command.WaitDelay = time.Second
	input, err := command.StdinPipe()
	if err != nil {
		return config, fmt.Errorf("CODEX_CONFIGURATION_UNAVAILABLE")
	}
	output, err := command.StdoutPipe()
	if err != nil {
		input.Close()
		return config, fmt.Errorf("CODEX_CONFIGURATION_UNAVAILABLE")
	}
	if err = command.Start(); err != nil {
		input.Close()
		output.Close()
		return config, fmt.Errorf("CODEX_CONFIGURATION_UNAVAILABLE")
	}
	done := make(chan error, 1)
	go func() { done <- command.Wait() }()
	defer func() {
		input.Close()
		select {
		case <-done:
		case <-time.After(time.Second):
			_ = command.Process.Kill()
			<-done
		}
	}()
	encoder, decoder := json.NewEncoder(input), json.NewDecoder(io.LimitReader(output, 8_000_000))
	send := func(id int, method string, params any) error {
		return encoder.Encode(map[string]any{"id": id, "method": method, "params": params})
	}
	receive := func(id int, destination any) error {
		for range 128 {
			var envelope struct {
				ID     *int            `json:"id"`
				Method string          `json:"method"`
				Result json.RawMessage `json:"result"`
				Error  json.RawMessage `json:"error"`
			}
			if decoder.Decode(&envelope) != nil {
				break
			}
			if envelope.ID != nil && *envelope.ID == id && envelope.Method == "" {
				if len(envelope.Error) != 0 {
					break
				}
				return json.Unmarshal(envelope.Result, destination)
			}
		}
		return fmt.Errorf("CODEX_CONFIGURATION_UNAVAILABLE")
	}
	if send(1, "initialize", map[string]any{"clientInfo": map[string]string{"name": "roami_lifecycle", "version": "1"}}) != nil || receive(1, &map[string]any{}) != nil {
		return config, fmt.Errorf("CODEX_CONFIGURATION_UNAVAILABLE")
	}
	if encoder.Encode(map[string]any{"method": "initialized", "params": map[string]any{}}) != nil || send(2, "config/read", map[string]any{"cwd": directory, "includeLayers": false}) != nil {
		return config, fmt.Errorf("CODEX_CONFIGURATION_UNAVAILABLE")
	}
	var response struct {
		Config json.RawMessage `json:"config"`
	}
	if receive(2, &response) != nil || len(response.Config) == 0 || json.Unmarshal(response.Config, &config) != nil {
		return config, fmt.Errorf("CODEX_CONFIGURATION_UNAVAILABLE")
	}
	return config, nil
}

func shellQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", `'\''`) + "'"
}

func callbackArguments(options SessionOptions, executor, sub string) []string {
	args := []string{options.Executable}
	for _, pair := range [][2]string{{"--home", options.HomeDir}, {"--data-dir", options.DataDir}, {"--database-dir", options.DatabaseDir}, {"--backup-dir", options.BackupDir}} {
		if pair[1] != "" {
			args = append(args, pair[0], pair[1])
		}
	}
	args = append(args, "agent", "execution", sub, "--executor", executor)
	if options.TmuxBin != "" {
		args = append(args, "--tmux-bin", options.TmuxBin)
	}
	return args
}
