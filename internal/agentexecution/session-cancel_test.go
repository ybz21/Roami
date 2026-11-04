package agentexecution

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func cancellationKeyLog(t *testing.T, s Service, fail bool) string {
	t.Helper()
	path := s.Runtime.TmuxBin
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	branch := `send-keys) printf '%s\n' "$*" >> "$root/keys"; `
	if fail {
		branch += `exit 1 ;;`
	} else {
		branch += `exit 0 ;;`
	}
	content := strings.Replace(string(raw), "send-keys|delete-buffer) exit 0 ;;", branch+"\n delete-buffer) exit 0 ;;", 1)
	if err = os.WriteFile(path, []byte(content), 0700); err != nil {
		t.Fatal(err)
	}
	return filepath.Join(s.Runtime.DataDir, "keys")
}

func TestSessionCancelInterruptsOnlyOnceAndStillNeedsStopEvidence(t *testing.T) {
	for _, provider := range []string{"codex", "claude"} {
		t.Run(provider, func(t *testing.T) {
			s, binding := sessionFixture(t)
			var spec Spec
			if provider == "codex" {
				seedSession(t, s, binding)
				spec, _ = startSessionTask(t, s, binding, "interrupt")
			} else {
				seedClaudeSession(t, s, binding)
				spec = startClaudeTask(t, s, binding, "interrupt")
			}
			keys := cancellationKeyLog(t, s, false)
			var callers sync.WaitGroup
			for range 4 {
				callers.Add(1)
				go func() {
					defer callers.Done()
					status, err := s.Cancel(spec.Key)
					if err != nil || status.State != "cancelling" || status.Result != nil {
						t.Errorf("cancel falsely settled: %+v %v", status, err)
					}
				}()
			}
			callers.Wait()
			input, err := os.ReadFile(keys)
			if err != nil || string(input) != "send-keys -t %3 Escape\n" {
				t.Fatalf("interrupt replayed or killed the TUI: %s %v", input, err)
			}
			status, err := s.Status(spec.Key)
			if err != nil || status.State != "cancelling" || status.Result != nil {
				t.Fatalf("delivery invented stop evidence: %+v %v", status, err)
			}
			var request sessionInterrupt
			dir, _ := s.directory(spec.Key)
			if err = readJSON(filepath.Join(dir, "interrupt-request.json"), &request); err != nil || !request.Delivered || request.TurnID == "" || request.ProviderID != "provider-thread" {
				t.Fatalf("missing bound interrupt receipt: %+v %v", request, err)
			}
		})
	}
}

func TestSessionCancelNeverInterruptsAnUncertainOrReusedTurn(t *testing.T) {
	for _, mode := range []string{"new-input", "other-launch", "other-provider", "other-prompt", "other-process", "other-pane", "other-directory", "unknown", "structured"} {
		t.Run(mode, func(t *testing.T) {
			s, binding := sessionFixture(t)
			seedSession(t, s, binding)
			spec, _ := startSessionTask(t, s, binding, "stale-cancel")
			keys := cancellationKeyLog(t, s, false)
			path, _ := s.lifecycleFile(binding)
			var state sessionLifecycle
			if err := readJSON(path, &state); err != nil {
				t.Fatal(err)
			}
			switch mode {
			case "new-input":
				if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: "provider-thread", TurnID: "manual-turn", Prompt: "user work"}); err != nil {
					t.Fatal(err)
				}
			case "other-launch":
				state.LaunchKey = "another-execution"
			case "other-provider":
				state.Binding.ProviderID = "another-provider"
			case "other-prompt":
				state.PromptHash = workspaceHash("another prompt")
			case "other-process":
				state.Binding.Processes[binding.PID] = "recycled-pid"
			case "other-pane", "other-directory":
				changed := binding
				if mode == "other-pane" {
					changed.Pane = "%99"
				} else {
					changed.Directory = t.TempDir()
				}
				identity := fmt.Sprintf("%s\t%s\t%s\t%s\t%s\t%d\t%s\n", changed.Name, changed.TmuxID, changed.Created, changed.Server, changed.Pane, changed.PID, changed.Directory)
				if err := os.WriteFile(filepath.Join(s.Runtime.DataDir, "identity"), []byte(identity), 0600); err != nil {
					t.Fatal(err)
				}
			case "unknown":
				state.State = "unknown"
			case "structured":
				state.Structured = true
			}
			if mode != "new-input" {
				if err := writeJSON(path, state); err != nil {
					t.Fatal(err)
				}
			}
			status, err := s.Cancel(spec.Key)
			if err != nil || status.Result != nil {
				t.Fatalf("cancel: %+v %v", status, err)
			}
			if input, _ := os.ReadFile(keys); len(input) != 0 {
				t.Fatalf("unsafe %s interrupt: %s", mode, input)
			}
		})
	}
}

func TestSessionCancelDoesNotReplayUnknownInputDelivery(t *testing.T) {
	s, binding := sessionFixture(t)
	seedSession(t, s, binding)
	spec, _ := startSessionTask(t, s, binding, "unknown-interrupt")
	keys := cancellationKeyLog(t, s, true)
	for range 2 {
		status, err := s.Cancel(spec.Key)
		if err != nil || status.State != "cancelling" || status.Result != nil || status.ObservationErrorCode != "SESSION_INTERRUPT_UNKNOWN" {
			t.Fatalf("uncertain interrupt claimed completion: %+v %v", status, err)
		}
	}
	input, err := os.ReadFile(keys)
	if err != nil || strings.Count(string(input), "Escape") != 1 {
		t.Fatalf("uncertain input replayed: %s %v", input, err)
	}
}

func TestSessionCancelRechecksThePaneBeforeSendingInput(t *testing.T) {
	s, binding := sessionFixture(t)
	seedSession(t, s, binding)
	spec, _ := startSessionTask(t, s, binding, "changed-binding")
	status, err := s.Status(spec.Key)
	if err != nil {
		t.Fatal(err)
	}
	keys := cancellationKeyLog(t, s, false)
	raw, err := os.ReadFile(s.Runtime.TmuxBin)
	if err != nil {
		t.Fatal(err)
	}
	branch := `list-panes|display-message)
 count=0; test ! -f "$root/identity-count" || count=$(cat "$root/identity-count")
 count=$((count+1)); printf '%s' "$count" > "$root/identity-count"
 if test "$count" -gt 1; then exit 1; fi
 cat "$root/identity" ;;`
	script := strings.Replace(string(raw), `list-panes|display-message) cat "$root/identity" ;;`, branch, 1)
	if err = os.WriteFile(s.Runtime.TmuxBin, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	status, err = s.cancelSession(spec.Key, status)
	if err != nil || status.State != "unknown" || status.ObservationErrorCode != "SESSION_BINDING_UNAVAILABLE" {
		t.Fatalf("stale identity accepted: %+v %v", status, err)
	}
	if input, _ := os.ReadFile(keys); len(input) != 0 {
		t.Fatalf("changed pane received input: %s", input)
	}
}

func TestSessionCancelAfterDeadlineStillInterruptsBoundTurn(t *testing.T) {
	for _, provider := range []string{"codex", "claude"} {
		t.Run(provider, func(t *testing.T) {
			s, binding := sessionFixture(t)
			var spec Spec
			if provider == "codex" {
				seedSession(t, s, binding)
				spec, _ = startSessionTask(t, s, binding, "expired-cancel")
			} else {
				seedClaudeSession(t, s, binding)
				spec = startClaudeTask(t, s, binding, "expired-cancel")
			}
			dir, _ := s.directory(spec.Key)
			var receipt Receipt
			if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
				t.Fatal(err)
			}
			receipt.DeadlineMS = 1
			if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
				t.Fatal(err)
			}
			before, err := s.Status(spec.Key)
			if err != nil || before.ObservationErrorCode != "EXECUTION_DEADLINE" {
				t.Fatalf("expected overdue observation: %+v %v", before, err)
			}
			keys := cancellationKeyLog(t, s, false)
			for range 2 {
				status, err := s.Cancel(spec.Key)
				if err != nil || status.State != "cancelling" || status.Result != nil || status.ObservationErrorCode != "" {
					t.Fatalf("deadline prevented cancellation: %+v %v", status, err)
				}
			}
			input, err := os.ReadFile(keys)
			if err != nil || string(input) != "send-keys -t %3 Escape\n" {
				t.Fatalf("overdue interrupt missing or replayed: %s %v", input, err)
			}
			status, err := s.Status(spec.Key)
			if err != nil || status.State != "cancelling" || status.Result != nil || status.ObservationErrorCode != "" {
				t.Fatalf("deadline hid pending cancellation: %+v %v", status, err)
			}
		})
	}
}

func TestSessionProviderConflictPreservesBoundIdentityAndCannotInterrupt(t *testing.T) {
	s, binding := sessionFixture(t)
	seedSession(t, s, binding)
	spec, _ := startSessionTask(t, s, binding, "provider-conflict")
	keys := cancellationKeyLog(t, s, false)
	event := SessionEvent{Hook: "PostToolUse", ProviderID: "foreign-thread", TurnID: "foreign-turn", ToolID: "foreign-tool", Prompt: "private input"}
	if err := s.applySessionEvent("codex", binding, event); err != nil {
		t.Fatal(err)
	}
	path, _ := s.lifecycleFile(binding)
	var state sessionLifecycle
	if err := readJSON(path, &state); err != nil {
		t.Fatal(err)
	}
	if state.UnknownReason != "SESSION_PROVIDER_CHANGED" || state.Binding.ProviderID != "provider-thread" || state.ProviderConflict == nil || state.ProviderConflict.ProviderID != "foreign-thread" || state.ProviderConflict.TurnID != "foreign-turn" || state.ProviderConflict.Hook != "PostToolUse" {
		t.Fatalf("missing identity-only conflict evidence: %+v", state)
	}
	raw, err := os.ReadFile(path)
	if err != nil || strings.Contains(string(raw), "private input") || strings.Contains(string(raw), "foreign-tool") {
		t.Fatalf("conflict leaked event content: %s %v", raw, err)
	}
	status, err := s.Cancel(spec.Key)
	if err != nil || status.State != "unknown" || status.ObservationErrorCode != "SESSION_PROVIDER_CHANGED" || status.Result != nil {
		t.Fatalf("provider conflict was accepted: %+v %v", status, err)
	}
	if input, _ := os.ReadFile(keys); len(input) != 0 {
		t.Fatalf("foreign callback caused interrupt: %s", input)
	}
}
