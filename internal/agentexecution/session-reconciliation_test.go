package agentexecution

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func changedInputFixture(t *testing.T) (Service, SessionBinding, Spec, []map[string]any) {
	t.Helper()
	s, binding := sessionFixture(t)
	pane := exec.Command("sleep", "120")
	if err := pane.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = pane.Process.Kill(); _ = pane.Wait() })
	binding.PID = pane.Process.Pid
	identity := fmt.Sprintf("%s\t%s\t%s\t%s\t%s\t%d\t%s\n", binding.Name, binding.TmuxID, binding.Created, binding.Server, binding.Pane, binding.PID, binding.Directory)
	if err := os.WriteFile(filepath.Join(s.Runtime.DataDir, "identity"), []byte(identity), 0600); err != nil {
		t.Fatal(err)
	}
	if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: completionThread, TurnID: "seed", Prompt: "manual"}); err != nil {
		t.Fatal(err)
	}
	if err := s.applySessionEvent("codex", binding, SessionEvent{Type: "agent-turn-complete", ThreadID: completionThread, NotificationTurn: "seed", Inputs: []string{"manual"}, LastAssistant: "Ready"}); err != nil {
		t.Fatal(err)
	}
	spec := Spec{Key: "changed-input", Executor: "codex", SessionID: binding.ID, Prompt: "Bound task"}
	status, err := s.Launch(context.Background(), spec)
	if err != nil || status.Binding == nil {
		t.Fatalf("launch: %+v %v", status, err)
	}
	binding = *status.Binding
	prompt, err := os.ReadFile(filepath.Join(s.Runtime.DataDir, "prompt"))
	if err != nil {
		t.Fatal(err)
	}
	if err = s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: completionThread, TurnID: "turn-1", Prompt: string(prompt)}); err != nil {
		t.Fatal(err)
	}
	if err = s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: completionThread, TurnID: "turn-1", Prompt: "Extra manual input"}); err != nil {
		t.Fatal(err)
	}
	records := completionRecords(binding, "turn-1", string(prompt))
	extra := map[string]any{"type": "response_item", "payload": map[string]any{"type": "message", "role": "user", "content": []any{map[string]any{"type": "input_text", "text": "Extra manual input"}}}}
	records = append(records[:5], append([]map[string]any{extra}, records[5:]...)...)
	t.Setenv("CODEX_HOME", t.TempDir())
	return s, binding, spec, records
}

func TestSessionChangedInputReconciliationKeepsFailureAndOriginalMember(t *testing.T) {
	s, binding, spec, records := changedInputFixture(t)
	saveCompletionRecords(t, os.Getenv("CODEX_HOME"), records)
	before, err := s.Status(spec.Key)
	if err != nil || before.State != "unknown" || before.Result != nil {
		t.Fatalf("ordinary status weakened: %+v %v", before, err)
	}
	path, _ := s.lifecycleFile(binding)
	var interrupted sessionLifecycle
	if err = readJSON(path, &interrupted); err != nil {
		t.Fatal(err)
	}
	submits, err := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
	if err != nil {
		t.Fatal(err)
	}
	settled, err := s.ReconcileSession(context.Background(), spec.Key)
	if err != nil || settled.State != "failed" || settled.Result == nil || settled.Result.Summary != "SESSION_SCOPE_CHANGED_STOPPED" || settled.Result.InputStopped == nil || !*settled.Result.InputStopped || settled.Result.OutcomeKnown == nil || !*settled.Result.OutcomeKnown || len(settled.Result.StopEvidence) != 64 {
		t.Fatalf("stop receipt: %+v %v", settled, err)
	}
	if settled.Binding.ProviderID != binding.ProviderID || settled.Binding.Pane != binding.Pane {
		t.Fatal("member replaced")
	}
	after, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
	if string(after) != string(submits) {
		t.Fatal("reconciliation replayed input")
	}
	again, err := s.ReconcileSession(context.Background(), spec.Key)
	if err != nil || again.State != "failed" || again.Result.StopEvidence != settled.Result.StopEvidence {
		t.Fatalf("replay: %+v %v", again, err)
	}
	if err = writeJSON(path, interrupted); err != nil {
		t.Fatal(err)
	}
	if _, err = s.ReconcileSession(context.Background(), spec.Key); err != nil {
		t.Fatal("interrupted lifecycle write was not recoverable", err)
	}
	next := spec
	next.Key = "bounded-followup"
	next.Prompt = "Reconcile existing files only"
	continued, err := s.Launch(context.Background(), next)
	if err != nil || continued.Binding == nil || continued.Binding.ProviderID != binding.ProviderID || continued.Binding.Pane != binding.Pane {
		t.Fatalf("original member not reusable: %+v %v", continued, err)
	}
	again, err = s.ReconcileSession(context.Background(), spec.Key)
	if err != nil || again.State != "failed" {
		t.Fatalf("old receipt after continuation: %+v %v", again, err)
	}
	var state sessionLifecycle
	if err = readJSON(path, &state); err != nil || state.LaunchKey != next.Key {
		t.Fatal("old reconciliation modified newer work", err)
	}
}

func TestSessionChangedInputReconciliationRejectsUnprovenStop(t *testing.T) {
	for _, mode := range []string{"no-extra-input", "wrong-provider", "wrong-directory", "wrong-root", "missing-final", "open-call", "new-turn", "wrong-prompt", "other-launch", "other-reason", "subagent", "unobserved-command", "process-running", "workspace-changed", "result-conflict"} {
		t.Run(mode, func(t *testing.T) {
			s, binding, spec, records := changedInputFixture(t)
			path, _ := s.lifecycleFile(binding)
			var state sessionLifecycle
			if err := readJSON(path, &state); err != nil {
				t.Fatal(err)
			}
			switch mode {
			case "no-extra-input":
				records = append(records[:5], records[6:]...)
			case "wrong-provider":
				records[0]["payload"].(map[string]any)["id"] = "another-provider"
			case "wrong-directory":
				records[0]["payload"].(map[string]any)["cwd"] = t.TempDir()
			case "wrong-root":
				records[len(records)-1]["payload"].(map[string]any)["root_turn_id"] = "foreign-turn"
			case "missing-final":
				records = records[:len(records)-1]
			case "open-call":
				records = append(records[:4], records[5:]...)
			case "new-turn":
				records = append(records, map[string]any{"type": "event_msg", "payload": map[string]any{"type": "task_started", "turn_id": "new-turn"}})
			case "wrong-prompt":
				state.PromptHash = workspaceHash("different")
			case "other-launch":
				state.LaunchKey = "other"
			case "other-reason":
				state.UnknownReason = "SESSION_PROVIDER_CHANGED"
			case "subagent":
				state.Tools = map[string]bool{"subagent:pending": true}
			case "unobserved-command":
				state.Tools = map[string]bool{"exec-00000000-0000-4000-8000-000000000002": true}
			case "process-running":
				state.Binding.Processes = map[int]string{}
			case "workspace-changed":
				root, release, err := s.lockWorkspaceWriter(context.Background(), binding.Directory)
				if err != nil {
					t.Fatal(err)
				}
				err = writeJSON(filepath.Join(root, "writer.json"), map[string]string{"key": "other"})
				release()
				if err != nil {
					t.Fatal(err)
				}
			case "result-conflict":
				dir, _ := s.directory(spec.Key)
				if err := writeJSON(filepath.Join(dir, "result.json"), Result{State: "succeeded", Summary: "another result"}); err != nil {
					t.Fatal(err)
				}
			}
			if err := writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			saveCompletionRecords(t, os.Getenv("CODEX_HOME"), records)
			before, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
			if result, err := s.ReconcileSession(context.Background(), spec.Key); err == nil {
				t.Fatalf("unproven stop accepted: %+v", result)
			}
			after, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
			if string(after) != string(before) {
				t.Fatal("rejected reconciliation sent input")
			}
			var current sessionLifecycle
			if err := readJSON(path, &current); err != nil || current.State != "unknown" {
				t.Fatal("unknown lifecycle cleared", err)
			}
		})
	}
}

func TestSessionChangedInputReconciliationRequiresObservedCommandCompletion(t *testing.T) {
	s, binding, spec, records := changedInputFixture(t)
	const command = "exec-00000000-0000-4000-8000-000000000002"
	path, _ := s.lifecycleFile(binding)
	var state sessionLifecycle
	if err := readJSON(path, &state); err != nil {
		t.Fatal(err)
	}
	state.Tools = map[string]bool{command: true}
	if err := writeJSON(path, state); err != nil {
		t.Fatal(err)
	}
	completed := map[string]any{"type": "event_msg", "payload": map[string]any{"type": "item_completed", "thread_id": binding.ProviderID, "turn_id": "turn-1", "started_at_ms": int64(1793013335000), "completed_at_ms": int64(1793013335600), "item": map[string]any{"type": "CommandExecution", "id": command, "process_id": "fixture", "status": "completed", "exit_code": 0}}}
	records = append(records[:6], append([]map[string]any{completed}, records[6:]...)...)
	saveCompletionRecords(t, os.Getenv("CODEX_HOME"), records)
	status, err := s.ReconcileSession(context.Background(), spec.Key)
	if err != nil || status.Result == nil || status.State != "failed" || strings.Contains(status.Result.Summary, "Verified result") {
		t.Fatalf("command stop proof: %+v %v", status, err)
	}
}
