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

func TestContinuationReconcilesCompletedDirectCodexMessage(t *testing.T) {
	for _, mode := range []string{"complete", "old-child-notify", "provider-change", "unfinished", "other-prompt", "other-turn", "other-provider", "other-directory", "new-user-input", "pending-tool", "pending-subagent", "stopped", "tracked-launch", "process-proof-mismatch", "proof-conflict"} {
		t.Run(mode, func(t *testing.T) {
			s, binding := sessionFixture(t)
			pane := exec.Command("sleep", "120")
			if err := pane.Start(); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { _ = pane.Process.Kill(); _ = pane.Wait() })
			binding.PID, binding.ProviderID = pane.Process.Pid, completionThread
			identity := fmt.Sprintf("%s\t%s\t%s\t%s\t%s\t%d\t%s\n", binding.Name, binding.TmuxID, binding.Created, binding.Server, binding.Pane, binding.PID, binding.Directory)
			if err := os.WriteFile(filepath.Join(s.Runtime.DataDir, "identity"), []byte(identity), 0600); err != nil {
				t.Fatal(err)
			}
			root := t.TempDir()
			t.Setenv("CODEX_HOME", root)
			_, scope, processes, err := paneProcessSnapshot(binding.PID)
			if err != nil {
				t.Fatal(err)
			}
			binding.Scope, binding.Processes = scope, processes
			// Existing tracked sessions retain the unrelated scope processes in their baseline.
			binding.ForeignProcesses = map[int]string{}
			for pid, token := range processes {
				if pid != binding.PID {
					binding.ForeignProcesses[pid] = token
				}
			}
			if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: completionThread, TurnID: "direct-turn", Prompt: "direct work"}); err != nil {
				t.Fatal(err)
			}
			path, err := s.lifecycleFile(binding)
			if err != nil {
				t.Fatal(err)
			}
			var state sessionLifecycle
			if err := readJSON(path, &state); err != nil {
				t.Fatal(err)
			}
			records := completionRecords(binding, "direct-turn", "direct work")
			switch mode {
			case "old-child-notify":
				state.ProviderConflict = &sessionProviderConflict{Executor: "codex", ProviderID: "child-provider", Type: "agent-turn-complete"}
			case "provider-change":
				state.State, state.UnknownReason = "unknown", "SESSION_PROVIDER_CHANGED"
			case "unfinished":
				records = records[:len(records)-1]
			case "other-prompt":
				state.PromptHash = workspaceHash("different work")
			case "other-turn":
				state.TurnID = "other-turn"
			case "other-provider":
				state.Binding.ProviderID = "00000000-0000-4000-8000-000000000002"
			case "other-directory":
				state.Binding.Directory = t.TempDir()
			case "new-user-input":
				records = append(records, map[string]any{"type": "event_msg", "payload": map[string]any{"type": "task_started", "turn_id": "new-turn"}})
			case "pending-tool":
				state.Tools["call-unknown"] = true
			case "pending-subagent":
				state.Tools["subagent:child"] = true
			case "stopped":
				state.State, state.UnknownReason = "unknown", "SESSION_INTERRUPTED"
			case "tracked-launch":
				state.LaunchKey = "other-tracked-task"
			case "process-proof-mismatch":
				state.Binding.Processes[binding.PID] = "unconfirmed-process-token"
			case "proof-conflict":
				proofPath := filepath.Join(filepath.Dir(path), "message-completions", workspaceHash(state.TurnID), "completion-source.json")
				if err := os.MkdirAll(filepath.Dir(proofPath), 0700); err != nil {
					t.Fatal(err)
				}
				if err := writeJSON(proofPath, completionSource{ProviderID: "conflict"}); err != nil {
					t.Fatal(err)
				}
			}
			saveCompletionRecords(t, root, records)
			if err := writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			spec := Spec{Key: "after-direct", Executor: "codex", SessionID: binding.ID, Prompt: "Next bounded task", TimeoutSeconds: 30}
			status, err := s.Launch(context.Background(), spec)
			submits, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
			if mode != "complete" && mode != "old-child-notify" {
				if err == nil || len(submits) != 0 {
					t.Fatalf("unsafe %s continuation: %+v %v %s", mode, status, err, submits)
				}
				var after sessionLifecycle
				if err := readJSON(path, &after); err != nil {
					t.Fatal(err)
				}
				if after.State != state.State || after.LaunchKey != state.LaunchKey || after.TurnID != state.TurnID {
					t.Fatalf("rejection changed lifecycle: %+v", after)
				}
				return
			}
			if err != nil || status.Binding == nil || status.Session != binding.ID || status.Binding.ProviderID != completionThread || strings.Count(string(submits), "submitted") != 1 {
				t.Fatalf("did not continue original instance once: %+v %v %s", status, err, submits)
			}
			if _, err := s.Launch(context.Background(), spec); err != nil {
				t.Fatal(err)
			}
			submits, _ = os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
			if strings.Count(string(submits), "submitted") != 1 {
				t.Fatal("duplicate submission")
			}
			var proof completionSource
			if err := readJSON(filepath.Join(filepath.Dir(path), "message-completions", workspaceHash("direct-turn"), "completion-source.json"), &proof); err != nil {
				t.Fatal(err)
			}
			if proof.ProviderID != completionThread || proof.TurnID != "direct-turn" || len(proof.TranscriptSHA256) != 64 {
				t.Fatalf("missing direct completion proof: %+v", proof)
			}
			if status.Result != nil {
				t.Fatal("direct message completion incorrectly completed next task")
			}
		})
	}
}
