package spawn

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func lifecycleBinary(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "codex")
	script := `#!/usr/bin/env python3
import json, os, sys
if sys.argv[1:] == ['--help']:
 print('--no-daemon --settings')
elif sys.argv[1:] == ['app-server', '--stdio']:
 for line in sys.stdin:
  request = json.loads(line)
  if 'id' not in request: continue
  result = {'config': {'notify': None}} if request['method'] == 'config/read' else {}
  print(json.dumps({'id': request['id'], 'result': result}), flush=True)
else:
 print(json.dumps(sys.argv[1:]))
`
	if err := os.WriteFile(path, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestPreparedInteractivePreservesArgumentsAndInstance(t *testing.T) {
	root := t.TempDir()
	workdir := filepath.Join(root, "work 'quoted'")
	if err := os.Mkdir(workdir, 0700); err != nil {
		t.Fatal(err)
	}
	config := AgentConfig{Kind: "codex", Interactive: true, Workdir: workdir, CodexBin: lifecycleBinary(t), Model: "fixture-model"}
	rt := runtime.Runtime{HomeDir: root, DataDir: root, TmuxBin: filepath.Join(root, "tmux fixture")}
	prepared, err := config.PrepareInteractive(rt)
	if err != nil {
		t.Fatal(err)
	}
	prompt := "two lines\nLiteral $(do-not-execute) and 'quotes'"
	promptFile := filepath.Join(root, "prompt 'file'")
	if err := os.WriteFile(promptFile, []byte(prompt), 0600); err != nil {
		t.Fatal(err)
	}
	output, err := exec.Command("sh", "-c", prepared.InteractiveFromPromptFile(promptFile)).CombinedOutput()
	if err != nil {
		t.Fatalf("launch failed: %v %s", err, output)
	}
	var args []string
	if err = json.Unmarshal(output, &args); err != nil {
		t.Fatal(err)
	}
	if args[0] != "-m" || args[1] != "fixture-model" || args[2] != "--no-daemon" || args[len(args)-1] != prompt {
		t.Fatalf("changed model or prompt: %q", args)
	}
	var notify struct {
		Notify []string `json:"notify"`
	}
	for index, arg := range args {
		if arg == "-c" && strings.HasPrefix(args[index+1], "notify=") {
			if err = json.Unmarshal([]byte(args[index+1][7:]), &notify.Notify); err != nil {
				t.Fatal(err)
			}
		}
	}
	joined := strings.Join(notify.Notify, "\n")
	for _, expected := range []string{"--home\n" + root, "--data-dir\n" + root, "--database-dir\n" + filepath.Join(root, "database"), "--tmux-bin\n" + rt.TmuxBin} {
		if !strings.Contains(joined, expected) {
			t.Fatalf("missing instance routing: %q", notify.Notify)
		}
	}
	if strings.Contains(strings.Join(args, " "), "bypass-hook-trust") {
		t.Fatal("hook trust bypassed")
	}
	resumeOutput, err := exec.Command("sh", "-c", prepared.ResumeInteractive("provider-thread")).CombinedOutput()
	if err != nil || json.Unmarshal(resumeOutput, &args) != nil {
		t.Fatalf("resume: %v %s", err, resumeOutput)
	}
	if args[len(args)-2] != "resume" || args[len(args)-1] != "provider-thread" {
		t.Fatal("lost resume identity")
	}
	if config.lifecycleArgs != nil {
		t.Fatal("preparation mutated shared configuration")
	}
}

func TestUnsupportedOrCancelledCodexKeepsOriginalLaunch(t *testing.T) {
	for _, cancelled := range []bool{false, true} {
		root := t.TempDir()
		ctx, cancel := context.WithCancel(context.Background())
		if cancelled {
			cancel()
		} else {
			defer cancel()
		}
		config := AgentConfig{Kind: "codex", Interactive: true, Workdir: root, CodexBin: "/bin/false"}
		prepared, err := config.PrepareInteractive(runtime.Runtime{HomeDir: root, DataDir: root, Context: ctx})
		if err == nil || len(prepared.lifecycleArgs) != 0 || prepared.Command("prompt") != config.Command("prompt") {
			t.Fatal("failed preparation changed launch")
		}
	}
	config := AgentConfig{Kind: "pi", Interactive: true, Workdir: t.TempDir()}
	if _, err := config.PrepareInteractive(runtime.Runtime{}); err != nil {
		t.Fatal("unrelated provider probed")
	}
	config.Kind, config.Interactive = "codex", false
	if _, err := config.PrepareInteractive(runtime.Runtime{}); err != nil {
		t.Fatal("one-shot provider probed")
	}
}

func TestClaudeScopedSettingsAndResumeKeepExactShellArguments(t *testing.T) {
	root := t.TempDir()
	binary := filepath.Join(root, "claude 'wrapper'")
	data, err := os.ReadFile(lifecycleBinary(t))
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(binary, data, 0700); err != nil {
		t.Fatal(err)
	}
	config := AgentConfig{Kind: "claude", Interactive: true, Workdir: root, ClaudeBin: binary, Model: "model $(must-not-run)", SessionUUID: "initial-session"}
	prepared, err := config.PrepareInteractive(runtime.Runtime{HomeDir: root, DataDir: root, TmuxBin: "tmux"})
	if err != nil {
		t.Fatal(err)
	}
	output, err := exec.Command("sh", "-c", prepared.Command("literal 'prompt'")).CombinedOutput()
	if err != nil {
		t.Fatalf("quoted executable or settings failed: %v %s", err, output)
	}
	var args []string
	if json.Unmarshal(output, &args) != nil {
		t.Fatal("invalid launch output")
	}
	if args[0] != "--model" || args[1] != config.Model || args[2] != "--session-id" || args[3] != "initial-session" || args[4] != "--settings" || args[len(args)-1] != "literal 'prompt'" {
		t.Fatalf("changed launch arguments: %q", args)
	}
	var settings map[string]any
	if json.Unmarshal([]byte(args[5]), &settings) != nil || len(settings) != 1 || settings["hooks"] == nil {
		t.Fatal("observers changed model or permission settings")
	}
	output, err = exec.Command("sh", "-c", prepared.ResumeInteractive("original-session")).CombinedOutput()
	if err != nil || json.Unmarshal(output, &args) != nil {
		t.Fatalf("resume failed: %v %s", err, output)
	}
	for _, arg := range args {
		if arg == "--session-id" {
			t.Fatal("resume created a different conversation")
		}
	}
	if args[len(args)-2] != "--resume" || args[len(args)-1] != "original-session" {
		t.Fatal("lost original conversation")
	}
}
