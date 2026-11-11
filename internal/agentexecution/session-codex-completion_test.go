package agentexecution

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

const completionThread = "00000000-0000-4000-8000-000000000001"

func completionRecords(binding SessionBinding, turn, prompt string) []map[string]any {
	record := func(kind string, payload map[string]any) map[string]any {
		return map[string]any{"type": kind, "timestamp": "2026-10-26T11:15:35.727Z", "payload": payload}
	}
	message := func(role, text string) map[string]any {
		return record("response_item", map[string]any{"type": "message", "role": role, "phase": "final_answer", "content": []any{map[string]any{"type": "input_text", "text": text}}})
	}
	return []map[string]any{
		record("session_meta", map[string]any{"id": binding.ProviderID, "cwd": binding.Directory}),
		record("event_msg", map[string]any{"type": "task_started", "turn_id": turn}),
		message("user", prompt),
		record("response_item", map[string]any{"type": "custom_tool_call", "call_id": "call-1"}),
		record("response_item", map[string]any{"type": "custom_tool_call_output", "call_id": "call-1"}),
		message("assistant", "Verified result"),
		record("event_msg", map[string]any{"type": "task_complete", "turn_id": turn, "root_turn_id": turn, "last_agent_message": "Verified result"}),
	}
}

func saveCompletionRecords(t *testing.T, root string, records []map[string]any) string {
	t.Helper()
	path := filepath.Join(root, "sessions", "2026", "10", "26", "rollout-2026-10-26T18-38-06-"+completionThread+".jsonl")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	var data []byte
	for _, r := range records {
		raw, err := json.Marshal(r)
		if err != nil {
			t.Fatal(err)
		}
		data = append(append(data, raw...), '\n')
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestCodexCompletionRequiresBoundCompleteTranscript(t *testing.T) {
	for _, mode := range []string{"valid", "valid-group-write", "wrong-provider", "wrong-directory", "wrong-turn", "wrong-root", "wrong-prompt", "unfinished-call", "extra-input", "new-turn", "wrong-summary", "missing-summary", "unknown-call", "duplicate-call", "ambiguous-file", "symlink", "writable", "partial", "later-record", "aborted", "commentary"} {
		t.Run(mode, func(t *testing.T) {
			root := t.TempDir()
			t.Setenv("CODEX_HOME", root)
			binding := SessionBinding{ProviderID: completionThread, Directory: t.TempDir()}
			records := completionRecords(binding, "turn-1", "task prompt")
			payload := func(i int) map[string]any { return records[i]["payload"].(map[string]any) }
			switch mode {
			case "wrong-provider":
				payload(0)["id"] = "other-thread"
			case "wrong-directory":
				payload(0)["cwd"] = t.TempDir()
			case "wrong-turn":
				payload(6)["turn_id"] = "other-turn"
			case "wrong-root":
				payload(6)["root_turn_id"] = "other-turn"
			case "wrong-prompt":
				records[2]["payload"].(map[string]any)["content"] = []any{map[string]any{"type": "input_text", "text": "other input"}}
			case "unfinished-call":
				records = append(records[:4], records[5:]...)
			case "extra-input":
				records = append(records[:5], append([]map[string]any{records[2]}, records[5:]...)...)
			case "new-turn":
				records = append(records, map[string]any{"type": "event_msg", "payload": map[string]any{"type": "task_started", "turn_id": "new-turn"}})
			case "aborted":
				records = append(records[:6], append([]map[string]any{{"type": "event_msg", "payload": map[string]any{"type": "turn_aborted"}}}, records[6:]...)...)
			case "commentary":
				payload(5)["phase"] = "commentary"
			case "wrong-summary":
				payload(6)["last_agent_message"] = "Unverified claim"
			case "missing-summary":
				payload(6)["last_agent_message"] = ""
			case "unknown-call":
				payload(3)["type"] = "unknown_call"
			case "duplicate-call":
				records = append(records[:4], append([]map[string]any{records[3]}, records[4:]...)...)
			case "later-record":
				records = append(records, map[string]any{"type": "event_msg", "payload": map[string]any{"type": "token_count"}})
			}
			path := saveCompletionRecords(t, root, records)
			switch mode {
			case "ambiguous-file":
				raw, _ := os.ReadFile(path)
				other := strings.Replace(path, "/26/", "/25/", 1)
				if err := os.MkdirAll(filepath.Dir(other), 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(other, raw, 0600); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				other := path + ".original"
				if err := os.Rename(path, other); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(other, path); err != nil {
					t.Fatal(err)
				}
			case "valid-group-write":
				if err := os.Chmod(path, 0664); err != nil {
					t.Fatal(err)
				}
			case "writable":
				if err := os.Chmod(path, 0666); err != nil {
					t.Fatal(err)
				}
			case "partial":
				file, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0600)
				if err != nil {
					t.Fatal(err)
				}
				_, _ = file.WriteString("{\"type\":")
				_ = file.Close()
			}
			result, hash := codexCompletion(binding, "turn-1", workspaceHash("task prompt"))
			if mode == "valid" || mode == "valid-group-write" {
				if result == nil || result.Summary != "Verified result" || result.FinishedMS != 1793013335727 || len(hash) != 64 {
					t.Fatalf("result=%+v hash=%q", result, hash)
				}
			} else if result != nil {
				t.Fatalf("unsafe %s completion: %+v", mode, result)
			}
		})
	}
}

func TestCodexCompletionIgnoresEarlierCompletedTurns(t *testing.T) {
	root := t.TempDir()
	t.Setenv("CODEX_HOME", root)
	binding := SessionBinding{ProviderID: completionThread, Directory: t.TempDir()}
	records := append(completionRecords(binding, "old-turn", "old input"), completionRecords(binding, "current-turn", "current input")...)
	saveCompletionRecords(t, root, records)
	result, _ := codexCompletion(binding, "current-turn", workspaceHash("current input"))
	if result == nil {
		t.Fatal("earlier turn prevented current completion")
	}
}

func TestCodexCompletionReconcilesWithoutResubmission(t *testing.T) {
	for _, mode := range []string{"unknown", "busy", "cancelled", "cancelled-manual-input", "lost-post-hook", "pending-subagent", "evidence-conflict", "aborted", "aborted-without-request", "aborted-other-turn", "aborted-live-process", "aborted-manual-input", "aborted-pending-hook", "aborted-pending-hook-unbound", "aborted-pending-subagent", "native-completed-hook", "native-failed-hook", "native-cancelled-hook", "native-foreign-provider", "native-foreign-turn", "native-running-hook", "native-missing-exit", "native-future-hook", "native-missing-process", "native-duplicate-hook", "native-noncommand", "native-unobserved-hook", "native-pending-subagent", "native-live-process", "native-multiple-commands", "native-partial-commands", "native-reversed-time", "native-no-thread-id", "native-no-turn-id"} {
		t.Run(mode, func(t *testing.T) {
			cancelled := strings.HasPrefix(mode, "cancelled") || strings.HasPrefix(mode, "aborted") && mode != "aborted-without-request" || mode == "native-cancelled-hook"
			s, binding := sessionFixture(t)
			// The pane must not own unrelated subprocesses of the Go test runner.
			pane := exec.Command("sleep", "120")
			if err := pane.Start(); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() {
				_ = pane.Process.Kill()
				_ = pane.Wait()
			})
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
			spec := Spec{Key: "reconciled", Executor: "codex", SessionID: binding.ID, Prompt: "Work", TimeoutSeconds: 30}
			if _, err := s.Launch(context.Background(), spec); err != nil {
				t.Fatal(err)
			}
			prompt, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "prompt"))
			if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: completionThread, TurnID: "turn-1", Prompt: string(prompt)}); err != nil {
				t.Fatal(err)
			}
			path, _ := s.lifecycleFile(binding)
			var state sessionLifecycle
			if err := readJSON(path, &state); err != nil {
				t.Fatal(err)
			}
			state.State = "unknown"
			if mode == "busy" {
				state.State = "busy"
			}
			if mode == "lost-post-hook" {
				state.Tools = map[string]bool{"call-1": true}
			}
			if mode == "pending-subagent" || mode == "aborted-pending-subagent" {
				state.Tools = map[string]bool{"subagent:child": true}
			}
			if strings.HasPrefix(mode, "aborted-pending-hook") {
				state.Tools = map[string]bool{"exec-pending": true}
			}
			if mode == "aborted-manual-input" || mode == "cancelled-manual-input" {
				state.UnknownReason = "SESSION_PROMPT_MISMATCH"
			}
			if mode == "aborted" {
				state.UnknownReason = "SESSION_INTERRUPTED"
			}
			native := strings.HasPrefix(mode, "native-")
			const commandID = "exec-00000000-0000-4000-8000-000000000002"
			if native {
				state.Tools = map[string]bool{commandID: true}
				if mode == "native-multiple-commands" || mode == "native-partial-commands" {
					state.Tools["exec-00000000-0000-4000-8000-000000000003"] = true
				}
				if mode == "native-pending-subagent" {
					state.Tools["subagent:child"] = true
				}
			}
			if err := writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			t.Setenv("CODEX_HOME", t.TempDir())
			binding.ProviderID = completionThread
			records := completionRecords(binding, "turn-1", string(prompt))
			if native && mode != "native-unobserved-hook" {
				item := map[string]any{"type": "CommandExecution", "id": commandID, "process_id": "123", "status": "completed", "exit_code": 0}
				payload := map[string]any{"type": "item_completed", "thread_id": completionThread, "turn_id": "turn-1", "started_at_ms": int64(1793013335000), "completed_at_ms": int64(1793013335600), "item": item}
				switch mode {
				case "native-failed-hook":
					item["status"], item["exit_code"] = "failed", 143
				case "native-foreign-provider":
					payload["thread_id"] = "other-provider"
				case "native-foreign-turn":
					payload["turn_id"] = "other-turn"
				case "native-running-hook":
					item["status"] = "inProgress"
				case "native-missing-exit":
					delete(item, "exit_code")
				case "native-future-hook":
					payload["completed_at_ms"] = int64(1793013336000)
				case "native-missing-process":
					delete(item, "process_id")
				case "native-noncommand":
					item["type"] = "AgentMessage"
				case "native-reversed-time":
					payload["started_at_ms"] = int64(1793013335700)
				case "native-no-thread-id":
					delete(payload, "thread_id")
				case "native-no-turn-id":
					delete(payload, "turn_id")
				}
				command := map[string]any{"type": "event_msg", "timestamp": "2026-10-26T11:15:35.600Z", "payload": payload}
				inserted := []map[string]any{command}
				if mode == "native-duplicate-hook" {
					inserted = append(inserted, command)
				}
				if mode == "native-multiple-commands" {
					otherItem := map[string]any{"type": "CommandExecution", "id": "exec-00000000-0000-4000-8000-000000000003", "process_id": "124", "status": "failed", "exit_code": 143}
					otherPayload := map[string]any{"type": "item_completed", "thread_id": completionThread, "turn_id": "turn-1", "started_at_ms": int64(1793013335001), "completed_at_ms": int64(1793013335601), "item": otherItem}
					inserted = append(inserted, map[string]any{"type": "event_msg", "timestamp": "2026-10-26T11:15:35.601Z", "payload": otherPayload})
				}
				records = append(records[:6], append(inserted, records[6:]...)...)
			}
			if strings.HasPrefix(mode, "aborted") {
				abort := map[string]any{"type": "event_msg", "timestamp": "2026-10-26T11:15:35.727Z", "payload": map[string]any{"type": "turn_aborted", "turn_id": "turn-1", "reason": "interrupted"}}
				if mode == "aborted-other-turn" {
					abort["payload"].(map[string]any)["turn_id"] = "other-turn"
				}
				records = append(records[:5], abort)
			}
			saveCompletionRecords(t, os.Getenv("CODEX_HOME"), records)
			dir, _ := s.directory(spec.Key)
			if mode == "aborted-pending-hook" || mode == "aborted-pending-subagent" {
				intent := sessionInterrupt{ResourceID: state.Binding.resourceID(), ProviderID: state.Binding.ProviderID, TurnID: state.TurnID, PromptHash: state.PromptHash, Delivered: true, ToolSignalsDelivered: true}
				if err := writeJSON(filepath.Join(dir, "interrupt-request.json"), intent); err != nil {
					t.Fatal(err)
				}
			}
			if cancelled {
				if err := os.WriteFile(filepath.Join(dir, "cancel.json"), []byte("{}"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if mode == "aborted-live-process" || mode == "native-live-process" {
				var receipt Receipt
				if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
					t.Fatal(err)
				}
				receipt.Binding.Processes[binding.PID] = "unconfirmed-process-token"
				if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
					t.Fatal(err)
				}
			}
			if mode == "evidence-conflict" {
				if err := writeJSON(filepath.Join(dir, "completion-source.json"), completionSource{ProviderID: completionThread, TurnID: "turn-1", TranscriptSHA256: "conflicting"}); err != nil {
					t.Fatal(err)
				}
				status, err := s.Status(spec.Key)
				if err == nil || err.Error() != "SESSION_COMPLETION_EVIDENCE_CHANGED" || status.Result != nil {
					t.Fatalf("conflicting proof accepted: %v", err)
				}
				if _, err := os.Stat(filepath.Join(dir, "result.json")); !os.IsNotExist(err) {
					t.Fatal("conflicting proof published a result")
				}
				return
			}
			status, err := s.Status(spec.Key)
			invalidNative := native && mode != "native-completed-hook" && mode != "native-failed-hook" && mode != "native-cancelled-hook" && mode != "native-multiple-commands"
			if invalidNative || mode == "lost-post-hook" || mode == "pending-subagent" || mode == "aborted-without-request" || mode == "aborted-other-turn" || mode == "aborted-live-process" || mode == "aborted-manual-input" || mode == "cancelled-manual-input" || mode == "aborted-pending-hook-unbound" || mode == "aborted-pending-subagent" {
				if err != nil || status.Result != nil || status.State != "unknown" {
					t.Fatalf("pending work accepted: %v", err)
				}
				return
			}
			if err != nil || status.Result == nil {
				t.Fatalf("reconcile: %+v %v", status, err)
			}
			expected := "succeeded"
			if cancelled {
				expected = "cancelled"
			}
			if status.State != expected || status.Result.InputStopped == nil || !*status.Result.InputStopped {
				t.Fatalf("result: %+v", status)
			}
			again, err := s.Status(spec.Key)
			if err != nil || again.Result.FinishedMS != status.Result.FinishedMS {
				t.Fatal("result was not stable")
			}
			submits, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
			if strings.Count(string(submits), "submitted") != 1 {
				t.Fatal("input replayed")
			}
			state = sessionLifecycle{}
			if err := readJSON(path, &state); err != nil || state.State != "idle" || state.LaunchKey != "" {
				t.Fatalf("session not recovered: state=%s key=%s error=%v", state.State, state.LaunchKey, err)
			}
		})
	}
}

func TestCodexCompletionLongLivedTranscript(t *testing.T) {
	root := t.TempDir()
	t.Setenv("CODEX_HOME", root)
	binding := SessionBinding{ProviderID: completionThread, Directory: t.TempDir()}
	records := completionRecords(binding, "turn-1", "task prompt")
	path := saveCompletionRecords(t, root, records[:1])
	file, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	// Historical token records grow persistent sessions without changing the bound turn.
	padding := []byte(`{"type":"event_msg","payload":{"type":"token_count","padding":"` + strings.Repeat("x", 64<<10) + `"}}` + "\n")
	for i := 0; i < 1025; i++ {
		if _, err := file.Write(padding); err != nil {
			t.Fatal(err)
		}
	}
	for _, record := range records[1:] {
		body, err := json.Marshal(record)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := file.Write(append(body, '\n')); err != nil {
			t.Fatal(err)
		}
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	result, proof := codexCompletion(binding, "turn-1", workspaceHash("task prompt"))
	if result == nil || result.State != "succeeded" || result.Summary != "Verified result" || len(proof) != 64 {
		t.Fatalf("long-lived terminal transcript not reconciled: result=%+v proof=%q", result, proof)
	}
	if err := os.Truncate(path, maxCodexTranscriptBytes+1); err != nil {
		t.Fatal(err)
	}
	if result, proof := codexCompletion(binding, "turn-1", workspaceHash("task prompt")); result != nil || proof != "" {
		t.Fatal("oversized transcript was accepted")
	}
}
