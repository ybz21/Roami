package agentexecution

import (
	"os"
	"path/filepath"
	"testing"
)

func TestUnknownLifecycleStillHonorsCancellationFence(t *testing.T) {
	for _, executor := range []string{"codex", "claude"} {
		t.Run(executor, func(t *testing.T) {
			s, binding := sessionFixture(t)
			var spec Spec
			turn := "task-turn"
			if executor == "codex" {
				seedSession(t, s, binding)
				spec, _ = startSessionTask(t, s, binding, "unknown-cancel")
			} else {
				seedClaudeSession(t, s, binding)
				spec = startClaudeTask(t, s, binding, "unknown-cancel")
				turn = "task-prompt"
			}
			event := SessionEvent{Hook: "PreToolUse", ProviderID: "provider-thread", TurnID: turn, PromptID: turn, ToolID: "in-flight"}
			if err := s.applySessionEvent(executor, binding, event); err != nil {
				t.Fatal(err)
			}
			event.Hook, event.TurnID, event.PromptID = "PostToolUse", "wrong-turn", "wrong-turn"
			if err := s.applySessionEvent(executor, binding, event); err != nil {
				t.Fatal(err)
			}
			status, err := s.Cancel(spec.Key)
			if err != nil || status.State != "unknown" || status.Result != nil {
				t.Fatalf("unknown is not stopped: %+v, %v", status, err)
			}
			event.Hook, event.TurnID, event.PromptID, event.ToolID = "PreToolUse", turn, turn, "must-not-start"
			if err = s.applySessionEvent(executor, binding, event); err == nil || err.Error() != "SESSION_TASK_CANCEL_REQUESTED" {
				t.Fatalf("unknown lifecycle bypassed cancellation: %v", err)
			}
			if status.ObservationErrorCode != "SESSION_TOOL_EVENT_MISMATCH" {
				t.Fatalf("unknown observation lost its cause: %+v", status)
			}
			path, _ := s.lifecycleFile(binding)
			var state sessionLifecycle
			if err = readJSON(path, &state); err != nil {
				t.Fatal(err)
			}
			if state.State != "unknown" || !state.Tools["in-flight"] || state.Tools["must-not-start"] {
				t.Fatalf("cancellation invented stop evidence: %+v", state)
			}
			event.ProviderID = "unrelated-provider"
			if err = s.applySessionEvent(executor, binding, event); err != nil {
				t.Fatalf("cancel fence leaked to another provider: %v", err)
			}
			if err = readJSON(path, &state); err != nil || state.UnknownReason != "SESSION_TOOL_EVENT_MISMATCH" {
				t.Fatalf("first unknown reason lost: %+v %v", state, err)
			}
		})
	}
}

func TestSessionObservationDistinguishesUnknownReasons(t *testing.T) {
	for _, reason := range []string{"missing-lifecycle", "launch-mismatch", "deadline", "binding-missing"} {
		t.Run(reason, func(t *testing.T) {
			s, binding := sessionFixture(t)
			seedSession(t, s, binding)
			spec, _ := startSessionTask(t, s, binding, "observation")
			path, _ := s.lifecycleFile(binding)
			expected := ""
			switch reason {
			case "missing-lifecycle":
				if err := os.Remove(path); err != nil {
					t.Fatal(err)
				}
				expected = "SESSION_LIFECYCLE_UNAVAILABLE"
			case "launch-mismatch":
				var state sessionLifecycle
				if err := readJSON(path, &state); err != nil {
					t.Fatal(err)
				}
				state.LaunchKey = "other-launch"
				if err := writeJSON(path, state); err != nil {
					t.Fatal(err)
				}
				expected = "SESSION_LAUNCH_MISMATCH"
			case "deadline":
				dir, _ := s.directory(spec.Key)
				var receipt Receipt
				if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
					t.Fatal(err)
				}
				receipt.DeadlineMS = 1
				if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
					t.Fatal(err)
				}
				expected = "EXECUTION_DEADLINE"
			case "binding-missing":
				if err := os.Remove(filepath.Join(s.Runtime.DataDir, "identity")); err != nil {
					t.Fatal(err)
				}
				expected = "SESSION_BINDING_UNAVAILABLE"
			}
			status, err := s.Status(spec.Key)
			if err != nil || status.State != "unknown" || status.Result != nil || status.ObservationErrorCode != expected {
				t.Fatalf("lost observation reason: %+v, %v", status, err)
			}
		})
	}
}
