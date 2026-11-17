package agentexecution

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestClaudeRetriesMatchedIdleAfterChildExit(t *testing.T) {
	for _, legacy := range []bool{false, true} {
		t.Run(map[bool]string{false: "automatic", true: "explicit legacy"}[legacy], func(t *testing.T) {
			s, binding, spec, transcript, _ := rejectedClaudeTask(t)
			dir, _ := s.directory(spec.Key)
			records := reportRecords(binding, sessionPrompt(dir, spec))
			records[1]["cwd"] = binding.Directory
			writeReportRecords(t, transcript, records)
			path, _ := s.lifecycleFile(binding)
			var state sessionLifecycle
			if err := readJSON(path, &state); err != nil {
				t.Fatal(err)
			}
			state.State, state.UnknownReason = "busy", ""
			if err := writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			child := exec.Command("sleep", "30")
			if err := child.Start(); err != nil {
				t.Fatal(err)
			}
			defer func() { _ = child.Process.Kill(); _ = child.Wait() }()
			for _, hook := range []string{"Stop", "Notification"} {
				event := claudeEvent(hook, "prompt")
				event.ProviderID = reportProviderID
				event.NotificationType = "idle_prompt"
				event.StopAssistant = "Completed research"
				if err := s.applySessionEvent("claude", binding, event); err != nil {
					t.Fatal(err)
				}
			}
			blocked, err := s.Status(spec.Key)
			if err != nil || blocked.State != "unknown" || blocked.Result != nil {
				t.Fatalf("live process settled: %+v %v", blocked, err)
			}
			if legacy {
				if err := readJSON(path, &state); err != nil {
					t.Fatal(err)
				}
				state.ClaudeStop = nil
				if err := writeJSON(path, state); err != nil {
					t.Fatal(err)
				}
				if status, err := s.ReconcileSession(context.Background(), spec.Key); err == nil || status.Result != nil {
					t.Fatal("explicit confirmation accepted a live process")
				}
			} else if err := os.Remove(transcript); err != nil {
				t.Fatal(err)
			}
			_ = child.Process.Kill()
			_ = child.Wait()
			status, err := s.Status(spec.Key)
			if legacy {
				if err != nil || status.Result != nil {
					t.Fatalf("legacy report settled automatically: %+v %v", status, err)
				}
				status, err = s.ReconcileSession(context.Background(), spec.Key)
			}
			if err != nil || status.State != "succeeded" || status.Result == nil || status.Result.InputStopped == nil || !*status.Result.InputStopped || len(status.Result.StopEvidence) != 64 {
				t.Fatalf("stopped task not recovered: %+v %v", status, err)
			}
			again, err := s.Status(spec.Key)
			if err != nil || again.Result.FinishedMS != status.Result.FinishedMS {
				t.Fatal("recovery changed completion")
			}
			var final sessionLifecycle
			if err := readJSON(filepath.Join(filepath.Dir(path), "state.json"), &final); err != nil || final.State != "idle" || final.LaunchKey != "" {
				t.Fatal("lifecycle not settled", err)
			}
		})
	}
}

func TestClaudeLaterActivityInvalidatesDeferredIdle(t *testing.T) {
	for _, hook := range []string{"PreToolUse", "StopFailure", "UserPromptSubmit"} {
		state := sessionLifecycle{State: "unknown", UnknownReason: "SESSION_STOP_UNCONFIRMED", TurnID: "prompt", ClaudeStop: &claudeStop{PromptID: "prompt", Idle: true}}
		event := SessionEvent{Hook: hook, TurnID: "prompt"}
		observeClaudeStop(&state, &event)
		if state.UnknownReason == "SESSION_STOP_UNCONFIRMED" || state.ClaudeStop != nil {
			t.Fatalf("%s kept stale idle proof", hook)
		}
	}
}

func TestClaudeLegacyIdleUsesProviderActivityInsteadOfMetadataMtime(t *testing.T) {
	for _, mode := range []string{"metadata", "assistant", "request", "queued command", "untimed activity"} {
		t.Run(mode, func(t *testing.T) {
			s, binding, spec, transcript, _ := rejectedClaudeTask(t)
			dir, _ := s.directory(spec.Key)
			records := reportRecords(binding, sessionPrompt(dir, spec))
			before := time.Now().Add(-time.Minute)
			for _, record := range records {
				record["timestamp"] = before.Format(time.RFC3339Nano)
			}
			records[1]["cwd"] = binding.Directory
			records = append(records[:1], append([]map[string]any{{"type": "api-request-blob"}}, records[1:]...)...)
			path, _ := s.lifecycleFile(binding)
			var state sessionLifecycle
			if err := readJSON(path, &state); err != nil {
				t.Fatal(err)
			}
			state.State, state.UnknownReason, state.ClaudeStop = "unknown", "SESSION_STOP_UNCONFIRMED", nil
			state.UpdatedMS = time.Now().UnixMilli()
			later := time.Now().Add(time.Second)
			tail := map[string]any{"type": "cost-state", "timestamp": later.Format(time.RFC3339Nano)}
			switch mode {
			case "assistant", "untimed activity":
				tail = map[string]any{"type": "assistant", "sessionId": binding.ProviderID, "cwd": binding.Directory, "message": map[string]any{"stop_reason": "tool_use", "content": []any{map[string]any{"type": "tool_use", "id": "later-tool"}}}}
				if mode == "assistant" {
					tail["timestamp"] = later.Format(time.RFC3339Nano)
				}
			case "request":
				tail["type"] = "api-request"
			case "queued command":
				tail["type"] = "attachment"
				tail["attachment"] = map[string]any{"type": "queued_command"}
			}
			records = append(records, tail)
			writeReportRecords(t, transcript, records)
			if err := os.Chtimes(transcript, later, later); err != nil {
				t.Fatal(err)
			}
			if err := writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			status, err := s.ReconcileSession(context.Background(), spec.Key)
			if mode == "metadata" {
				if err != nil || status.Result == nil || status.Result.State != "succeeded" {
					t.Fatalf("metadata blocked bound idle: %+v %v", status, err)
				}
			} else if err == nil || status.Result != nil {
				t.Fatalf("later %s was accepted: %+v %v", mode, status, err)
			}
		})
	}
}
