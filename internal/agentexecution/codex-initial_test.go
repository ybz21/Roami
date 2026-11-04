package agentexecution

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"syscall"
	"testing"
	"time"

	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func initialController(t *testing.T, s Service, binding SessionBinding) (Spec, string) {
	t.Helper()
	spec := Spec{Key: "initial-codex:" + binding.ID, Executor: "codex", Directory: binding.Directory, Prompt: "Initial assigned work", Persistent: true}
	dir, _ := s.directory(spec.Key)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	for name, value := range map[string]any{"spec.json": spec, "receipt.json": Receipt{Session: binding.ID, State: "launched", Workspace: &Workspace{Directory: binding.Directory}}} {
		if err := writeJSON(filepath.Join(dir, name), value); err != nil {
			t.Fatal(err)
		}
	}
	prompt := sessionPrompt(dir, spec)
	if err := os.WriteFile(filepath.Join(dir, "prompt.txt"), []byte(prompt), 0600); err != nil {
		t.Fatal(err)
	}
	state := sessionLifecycle{InitialLaunch: true, Binding: binding, Executor: "codex", State: "submitting", LaunchKey: spec.Key, Tools: map[string]bool{}}
	path, _ := s.lifecycleFile(binding)
	if err := writeJSON(path, state); err != nil {
		t.Fatal(err)
	}
	return spec, prompt
}

func TestCodexInitialProcessFixture(t *testing.T) {
	if os.Getenv("ROAMI_INITIAL_FIXTURE") != "1" {
		return
	}
	var args []string
	for i, arg := range os.Args {
		if arg == "--" {
			args = os.Args[i+1:]
			break
		}
	}
	if len(args) != 4 {
		os.Exit(2)
	}
	ready, host, mode := args[1], args[2], args[3]
	child := exec.Command(host, "-test.run=TestCodeModeProcessFixture", "--", "host", ready+".host", "none")
	child.Env = append(os.Environ(), "ROAMI_CODE_MODE_FIXTURE=1")
	if child.Start() != nil {
		os.Exit(3)
	}
	defer func() { _ = child.Process.Signal(syscall.SIGTERM); _ = child.Wait() }()
	for until := time.Now().Add(5 * time.Second); ; {
		if _, err := os.Stat(ready + ".host"); err == nil {
			break
		}
		if time.Now().After(until) {
			os.Exit(4)
		}
		time.Sleep(10 * time.Millisecond)
	}
	if mode == "worker" {
		worker := exec.Command("sleep", "60")
		if worker.Start() != nil {
			os.Exit(5)
		}
		defer func() { _ = worker.Process.Kill(); _ = worker.Wait() }()
	}
	if mode == "orphan" {
		output, err := exec.Command("sh", "-c", "sleep 60 >/dev/null 2>&1 & echo $!").Output()
		if err != nil {
			os.Exit(6)
		}
		pid, _ := strconv.Atoi(string(bytes.TrimSpace(output)))
		defer func() {
			process, err := os.FindProcess(pid)
			if err == nil {
				_ = process.Signal(syscall.SIGTERM)
			}
		}()
	}
	if os.WriteFile(ready, []byte("ready"), 0600) != nil {
		os.Exit(7)
	}
	stopped := make(chan os.Signal, 1)
	signal.Notify(stopped, syscall.SIGTERM, syscall.SIGHUP)
	<-stopped
}

func initialRealFixture(t *testing.T, mode string) (Service, Spec, SessionBinding, []map[string]any) {
	t.Helper()
	rt := runtime.New()
	if rt.TmuxBin != filepath.Join(rt.DataDir, "tmux") {
		t.Skip("requires isolated launcher")
	}
	if _, err := os.Stat(filepath.Join(rt.DataDir, "tmux-instance.json")); err != nil {
		t.Skip("requires recorded private server")
	}
	directory, executables := t.TempDir(), t.TempDir()
	provider, host := filepath.Join(executables, "codex"), filepath.Join(executables, "codex-code-mode-host")
	copyCodeModeExecutable(t, provider)
	copyCodeModeExecutable(t, host)
	name, err := rt.CreateSession(runtime.CreateOpts{Dir: directory})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = rt.Tmux("kill-session", "-t", "="+name) })
	s := Service{Runtime: rt}
	binding, err := s.paneBinding(name, false)
	if err != nil {
		t.Fatal(err)
	}
	spec, prompt := initialController(t, s, binding)
	dir, _ := s.directory(spec.Key)
	if err := rt.Tmux("set-environment", "-t", "="+name, "ROAMI_AGENT_LAUNCH", filepath.Base(dir)); err != nil {
		t.Fatal(err)
	}
	ready := filepath.Join(directory, "ready")
	command := "ROAMI_INITIAL_FIXTURE=1 ROAMI_AGENT_LAUNCH=" + quote(filepath.Base(dir)) + " exec " + quote(provider) + " -test.run=TestCodexInitialProcessFixture -- " + quote(prompt) + " " + quote(ready) + " " + quote(host) + " " + quote(mode)
	if err := rt.SendPromptSubmit(binding.Pane, command); err != nil {
		t.Fatal(err)
	}
	waitCodeModeFile(t, ready)
	state := sessionLifecycle{InitialLaunch: true, Binding: binding, Executor: "codex", State: "unknown", UnknownReason: "SESSION_COMPLETION_MISMATCH", LaunchKey: spec.Key, Tools: map[string]bool{}, ProviderConflict: &sessionProviderConflict{Executor: "codex", ProviderID: completionThread, TurnID: "initial-turn", Hook: "PostToolUse"}}
	state.Binding.ProviderID = "unverified-startup"
	path, _ := s.lifecycleFile(binding)
	if err := writeJSON(path, state); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CODEX_HOME", t.TempDir())
	root := binding
	root.ProviderID = completionThread
	records := completionRecords(root, "initial-turn", prompt)
	stamp := time.Now().UTC().Format(time.RFC3339Nano)
	for _, record := range records {
		record["timestamp"] = stamp
	}
	metadata := records[0]["payload"].(map[string]any)
	metadata["source"], metadata["originator"] = "cli", "codex-tui"
	records[1]["payload"].(map[string]any)["root_turn_id"] = "initial-turn"
	return s, spec, binding, records
}

func TestInitialCodexRecoveryUsesOnlyAuthenticatedRootAndIdleResidents(t *testing.T) {
	for _, mode := range []string{"valid", "future-baseline", "unrelated-large", "worker", "orphan", "wrong-source", "wrong-originator", "wrong-input", "wrong-root-start", "changed-prompt-file", "missing-structured-final", "pending-tool", "new-user", "ambiguous-root", "wrong-marker", "wrong-pane-pid", "wrong-launch", "bound-receipt", "ordinary-unknown", "claude", "missing-process-token", "wrong-saved-token"} {
		t.Run(mode, func(t *testing.T) {
			processMode := mode
			if mode != "worker" && mode != "orphan" {
				processMode = "clean"
			}
			s, spec, binding, records := initialRealFixture(t, processMode)
			dir, _ := s.directory(spec.Key)
			path, _ := s.lifecycleFile(binding)
			var state sessionLifecycle
			if err := readJSON(path, &state); err != nil {
				t.Fatal(err)
			}
			switch mode {
			case "wrong-source":
				records[0]["payload"].(map[string]any)["source"] = map[string]any{"subagent": "worker"}
			case "wrong-originator":
				records[0]["payload"].(map[string]any)["originator"] = "other-client"
			case "wrong-input":
				records[2]["payload"].(map[string]any)["content"] = []any{map[string]any{"type": "input_text", "text": "different work"}}
			case "wrong-root-start":
				records[1]["payload"].(map[string]any)["root_turn_id"] = "other-root"
			case "changed-prompt-file":
				if err := os.WriteFile(filepath.Join(dir, "prompt.txt"), []byte("another assignment"), 0600); err != nil {
					t.Fatal(err)
				}
			case "missing-structured-final":
				records = records[:len(records)-1]
				if err := os.WriteFile(filepath.Join(binding.Directory, "claimed-result.json"), []byte(`{"state":"succeeded"}`), 0600); err != nil {
					t.Fatal(err)
				}
			case "future-baseline":
				snapshot, scope, _, err := paneProcessSnapshot(binding.PID)
				if err != nil {
					t.Fatal(err)
				}
				state.Binding.Scope = scope
				state.Binding.Processes = map[int]string{binding.PID: snapshot[binding.PID].Token}
			case "pending-tool":
				records = append(records[:4], records[5:]...)
			case "new-user":
				records = append(records[:5], append([]map[string]any{records[2]}, records[5:]...)...)
			case "wrong-marker":
				if err := s.Runtime.Tmux("set-environment", "-t", "="+binding.Name, "ROAMI_AGENT_LAUNCH", "other"); err != nil {
					t.Fatal(err)
				}
			case "wrong-pane-pid":
				state.Binding.PID++
			case "wrong-launch":
				state.LaunchKey = "another-launch"
			case "ordinary-unknown":
				state.InitialLaunch = false
				state.TurnID = "initial-turn"
				state.PromptHash = workspaceHash(sessionPrompt(dir, spec))
			case "claude":
				spec.Executor = "claude"
				state.Executor = "claude"
				if err := writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
					t.Fatal(err)
				}
			case "missing-process-token":
				state.Binding.Processes = map[int]string{binding.PID: ""}
			case "wrong-saved-token":
				state.Binding.Processes = map[int]string{binding.PID: "stale"}
			case "bound-receipt":
				var receipt Receipt
				if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
					t.Fatal(err)
				}
				receipt.Binding = &state.Binding
				if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
					t.Fatal(err)
				}
			}
			if err := writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			saveCompletionRecords(t, os.Getenv("CODEX_HOME"), records)
			if mode == "unrelated-large" {
				other := map[string]any{"type": "session_meta", "timestamp": time.Now().UTC().Format(time.RFC3339Nano), "payload": map[string]any{"id": "00000000-0000-4000-8000-000000000002", "source": "cli", "originator": "codex-tui", "cwd": t.TempDir()}}
				raw, _ := json.Marshal(other)
				p := filepath.Join(os.Getenv("CODEX_HOME"), "sessions", "2026", "10", "26", "rollout-unrelated-00000000-0000-4000-8000-000000000002.jsonl")
				if err := os.WriteFile(p, append(raw, '\n'), 0600); err != nil {
					t.Fatal(err)
				}
				if err := os.Truncate(p, (64<<20)+1); err != nil {
					t.Fatal(err)
				}
			}
			if mode == "ambiguous-root" {
				other := records[0]["payload"].(map[string]any)
				other["id"] = "00000000-0000-4000-8000-000000000002"
				raw, _ := json.Marshal(records[0])
				if err := os.WriteFile(filepath.Join(os.Getenv("CODEX_HOME"), "sessions", "2026", "10", "26", "rollout-other-00000000-0000-4000-8000-000000000002.jsonl"), append(raw, '\n'), 0600); err != nil {
					t.Fatal(err)
				}
			}
			status, err := s.Status(spec.Key)
			valid := mode == "valid" || mode == "future-baseline" || mode == "unrelated-large"
			if valid {
				if err != nil || status.Result == nil || status.State != "succeeded" || status.ObservationErrorCode != "" || status.Binding == nil || status.Binding.ProviderID != completionThread || status.Result.InputStopped == nil || !*status.Result.InputStopped {
					t.Fatalf("root not recovered: %+v %v", status, err)
				}
				var audit codexInitialObservation
				if err := readJSON(filepath.Join(dir, "initial-recovery.json"), &audit); err != nil || audit.ObservedAtRecovery == 0 || audit.Original.Binding.ProviderID != "unverified-startup" || audit.Original.UnknownReason != "SESSION_COMPLETION_MISMATCH" || audit.Binding.ProviderID != completionThread {
					t.Fatalf("lost recovery provenance: %+v %v", audit, err)
				}
				again, err := s.Status(spec.Key)
				if err != nil || again.Result.FinishedMS != status.Result.FinishedMS {
					t.Fatal("recovery not stable", err)
				}
			} else if err != nil || status.Result != nil {
				t.Fatalf("unsafe %s recovery: %+v %v", mode, status, err)
			}
		})
	}
}

func TestInitialCodexSessionStartCannotPinAnUnverifiedProvider(t *testing.T) {
	s, binding := sessionFixture(t)
	spec, prompt := initialController(t, s, binding)
	if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "SessionStart", ProviderID: "internal-thread"}); err != nil {
		t.Fatal(err)
	}
	if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: "internal-thread", TurnID: "internal-turn", Prompt: "internal classification"}); err != nil {
		t.Fatal(err)
	}
	path, _ := s.lifecycleFile(binding)
	var state sessionLifecycle
	if err := readJSON(path, &state); err != nil || state.Binding.ProviderID != "" || state.TurnID != "" || state.PromptHash != "" {
		t.Fatalf("unverified startup pinned identity: %+v %v", state, err)
	}
	if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: "actual-root", TurnID: "root-turn", Prompt: prompt}); err != nil {
		t.Fatal(err)
	}
	state = sessionLifecycle{}
	if err := readJSON(path, &state); err != nil || state.InitialLaunch || state.Binding.ProviderID != "actual-root" || state.TurnID != "root-turn" || state.PromptHash != workspaceHash(prompt) || state.LaunchKey != spec.Key || state.State != "busy" {
		t.Fatalf("root input lost behind startup candidate: %+v %v", state, err)
	}
	if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "PostToolUse", ProviderID: "other-thread", TurnID: "other-turn", ToolID: "other-tool"}); err != nil {
		t.Fatal(err)
	}
	state = sessionLifecycle{}
	if err := readJSON(path, &state); err != nil || state.State != "unknown" || state.UnknownReason != "SESSION_PROVIDER_CHANGED" || state.Binding.ProviderID != "actual-root" {
		t.Fatalf("bound provider guard relaxed: %+v %v", state, err)
	}
}

func TestInitialCodexInputRequiresOriginalControllerStartToken(t *testing.T) {
	s, binding := sessionFixture(t)
	spec, prompt := initialController(t, s, binding)
	path, _ := s.lifecycleFile(binding)
	var state sessionLifecycle
	if err := readJSON(path, &state); err != nil {
		t.Fatal(err)
	}
	state.Binding.Processes = map[int]string{binding.PID: "stale"}
	if err := writeJSON(path, state); err != nil {
		t.Fatal(err)
	}
	if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: "actual-root", TurnID: "root-turn", Prompt: prompt}); err == nil || err.Error() != "SESSION_BINDING_CONFLICT" {
		t.Fatal("recycled controller authenticated", err)
	}
	dir, _ := s.directory(spec.Key)
	var receipt Receipt
	if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil || receipt.Binding != nil {
		t.Fatal("stale process binding written", err)
	}
}

func TestInitialCodexControlSerializesCancelAndTerminalRecovery(t *testing.T) {
	for _, first := range []string{"cancel", "completion"} {
		t.Run(first, func(t *testing.T) {
			s, spec, _, records := initialRealFixture(t, "clean")
			dir, _ := s.directory(spec.Key)
			var receipt Receipt
			if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
				t.Fatal(err)
			}
			saveCompletionRecords(t, os.Getenv("CODEX_HOME"), records)
			if first == "completion" {
				finished, err := s.Status(spec.Key)
				if err != nil || finished.Result == nil {
					t.Fatalf("completion: %+v %v", finished, err)
				}
			}
			cancelled, handled, err := s.cancelInitialCodex(spec.Key, Status{Receipt: receipt})
			if err != nil || !handled {
				t.Fatal("cancel admission", err)
			}
			status, err := s.Status(spec.Key)
			if err != nil {
				t.Fatal(err)
			}
			if first == "cancel" {
				if cancelled.State != "cancelling" || status.Result != nil || status.State != "unknown" {
					t.Fatalf("cancel lost race: %+v %+v", cancelled, status)
				}
			} else {
				if cancelled.Result == nil || cancelled.Result.FinishedMS != status.Result.FinishedMS {
					t.Fatal("stale cancel overwrote completion")
				}
				if _, err := os.Stat(filepath.Join(dir, "cancel.json")); !os.IsNotExist(err) {
					t.Fatal("cancel created after terminal proof", err)
				}
			}
		})
	}
}

func TestInitialCodexCancelWaitsForControlLock(t *testing.T) {
	s, binding := sessionFixture(t)
	spec, _ := initialController(t, s, binding)
	dir, _ := s.directory(spec.Key)
	var receipt Receipt
	if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
		t.Fatal(err)
	}
	unlock, err := lock(filepath.Join(dir, "initial-control.lock"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		if unlock != nil {
			unlock()
		}
	}()
	done := make(chan error, 1)
	go func() { _, _, err := s.cancelInitialCodex(spec.Key, Status{Receipt: receipt}); done <- err }()
	select {
	case err := <-done:
		t.Fatal("control lock bypassed", err)
	case <-time.After(30 * time.Millisecond):
	}
	if _, err := os.Stat(filepath.Join(dir, "cancel.json")); !os.IsNotExist(err) {
		t.Fatal("cancel written outside key lock", err)
	}
	unlock()
	unlock = nil
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("cancel deadlocked")
	}
}
