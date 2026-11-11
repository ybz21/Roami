//go:build linux

package agentexecution

import (
	"os/exec"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func claudeCancellationWorker(t *testing.T) (*exec.Cmd, <-chan error) {
	t.Helper()
	command := exec.Command("sleep", "30")
	if err := command.Start(); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() {
		done <- command.Wait()
		close(done)
	}()
	t.Cleanup(func() {
		_ = command.Process.Kill()
		// Reap fixture children before the next case takes a process snapshot.
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Error("fixture worker not reaped")
		}
	})
	return command, done
}

func TestClaudeRejectedCancellationStopsOnlyNewOwnedProcesses(t *testing.T) {
	for _, changed := range []bool{false, true} {
		t.Run(map[bool]string{false: "original prompt", true: "changed input"}[changed], func(t *testing.T) {
			baseline, _ := claudeCancellationWorker(t)
			s, binding, spec, path, records := rejectedClaudeTask(t)
			if changed {
				event := claudeEvent("UserPromptSubmit", "followup")
				event.ProviderID = reportProviderID
				event.Prompt = "Continue"
				if err := s.applySessionEvent("claude", binding, event); err != nil {
					t.Fatal(err)
				}
				dir, _ := s.directory(spec.Key)
				records = claudeChangedFailureRecords(binding, sessionPrompt(dir, spec), "prompt", true)
			}
			writeReportRecords(t, path, records)
			worker, done := claudeCancellationWorker(t)
			status, err := s.Cancel(spec.Key)
			if err != nil || status.State != "cancelling" || status.Result != nil {
				t.Fatalf("cancel did not remain unconfirmed: %+v %v", status, err)
			}
			select {
			case err := <-done:
				if err == nil {
					t.Fatal("worker unexpectedly exited normally")
				}
			case <-time.After(5 * time.Second):
				t.Fatal("owned worker not stopped")
			}
			if baseline.Process.Signal(syscall.Signal(0)) != nil {
				t.Fatal("baseline provider infrastructure was stopped")
			}
			dir, _ := s.directory(spec.Key)
			var journal claudeRejectionInterrupt
			if err := readJSON(filepath.Join(dir, "rejection-interrupt.json"), &journal); err != nil || !journal.Signalled || len(journal.Processes) != 1 || journal.Processes[worker.Process.Pid] == "" || len(journal.Evidence) != 64 {
				t.Fatalf("incorrect scoped journal %+v %v", journal, err)
			}
			if _, exists := journal.Processes[binding.PID]; exists {
				t.Fatal("provider was targeted")
			}
			if changed {
				status, err = s.ReconcileSession(t.Context(), spec.Key)
			} else {
				status, err = s.Status(spec.Key)
			}
			if err != nil || status.Result == nil || status.Result.InputStopped == nil || !*status.Result.InputStopped || status.Binding.ProviderID != reportProviderID {
				t.Fatalf("actual stop not confirmed: %+v %v", status, err)
			}
			spec.Key = "after-rejected-cancel"
			spec.Prompt = "Continue evidence collection"
			next, err := s.Launch(t.Context(), spec)
			if err != nil || next.Session != binding.ID || next.Binding.ProviderID != reportProviderID {
				t.Fatalf("provider not retained: %+v %v", next, err)
			}
		})
	}
}

func TestClaudeRejectedCancellationNeverSignalsUnprovedOrUncertainRequests(t *testing.T) {
	for _, mode := range []string{"normal response", "server error", "pending tool", "uncertain signal", "different evidence"} {
		t.Run(mode, func(t *testing.T) {
			s, binding, spec, path, records := rejectedClaudeTask(t)
			switch mode {
			case "normal response":
				records[1]["message"].(map[string]any)["model"] = "real-model"
			case "server error":
				records[1]["apiErrorStatus"] = 500
			case "pending tool":
				file, _ := s.lifecycleFile(binding)
				var state sessionLifecycle
				if err := readJSON(file, &state); err != nil {
					t.Fatal(err)
				}
				state.Tools["pending"] = true
				if err := writeJSON(file, state); err != nil {
					t.Fatal(err)
				}
			}
			writeReportRecords(t, path, records)
			worker, done := claudeCancellationWorker(t)
			if mode == "uncertain signal" || mode == "different evidence" {
				file, _ := s.lifecycleFile(binding)
				var state sessionLifecycle
				if err := readJSON(file, &state); err != nil {
					t.Fatal(err)
				}
				_, digest := claudeRejectedResponse(state.Binding, state.TurnID, state.PromptHash)
				if digest == "" {
					t.Fatal("fixture proof missing")
				}
				if mode == "different evidence" {
					digest = "different"
				}
				request := claudeRejectionInterrupt{ResourceID: binding.resourceID(), ProviderID: reportProviderID, TurnID: state.TurnID, PromptHash: state.PromptHash, Evidence: digest, Processes: map[int]string{worker.Process.Pid: "captured"}}
				dir, _ := s.directory(spec.Key)
				if err := writeJSON(filepath.Join(dir, "rejection-interrupt.json"), request); err != nil {
					t.Fatal(err)
				}
			}
			status, err := s.Cancel(spec.Key)
			if mode == "different evidence" {
				if err == nil {
					t.Fatal("changed evidence accepted")
				}
			} else if err != nil || status.Result != nil || status.State != "unknown" {
				t.Fatalf("unproved cancellation accepted: %+v %v", status, err)
			}
			if mode == "uncertain signal" && status.ObservationErrorCode != "SESSION_TOOL_INTERRUPT_UNKNOWN" {
				t.Fatal("uncertain signal was replayed")
			}
			select {
			case <-done:
				t.Fatal("unproved child was stopped")
			case <-time.After(50 * time.Millisecond):
			}
		})
	}
}
