package agentexecution

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
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
