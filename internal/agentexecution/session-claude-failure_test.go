package agentexecution

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func claudeFailureRecords(binding SessionBinding, prompt, turn string) []map[string]any {
	stamp := time.Now().Add(-time.Second)
	return []map[string]any{
		{"type": "user", "sessionId": binding.ProviderID, "promptId": turn, "cwd": binding.Directory, "timestamp": stamp.Format(time.RFC3339Nano), "message": map[string]any{"content": prompt}},
		{"type": "assistant", "uuid": "error-message", "sessionId": binding.ProviderID, "cwd": binding.Directory, "timestamp": stamp.Add(time.Millisecond).Format(time.RFC3339Nano), "isApiErrorMessage": true, "failedResponseHadNoToolCall": true, "apiErrorStatus": 400, "message": map[string]any{"model": "<synthetic>", "role": "assistant", "stop_reason": "stop_sequence", "usage": map[string]any{"input_tokens": 0, "output_tokens": 0}, "content": []any{map[string]any{"type": "text", "text": "API Error: 400 configuration rejected"}}}},
		{"type": "system", "subtype": "turn_duration", "parentUuid": "error-message", "sessionId": binding.ProviderID, "cwd": binding.Directory, "timestamp": stamp.Add(2 * time.Millisecond).Format(time.RFC3339Nano), "durationMs": 2},
	}
}

func TestClaudeRejectedFirstResponseProof(t *testing.T) {
	binding, path, _, prompt := reportFixture(t)
	records := claudeFailureRecords(binding, prompt, "prompt")
	records = append(records[:1], append([]map[string]any{{"type": "attachment", "attachment": map[string]any{"type": "environment"}}, {"type": "api-request"}}, records[1:]...)...)
	records = append(records, map[string]any{"type": "last-prompt"})
	writeReportRecords(t, path, records)
	result, digest := claudeRejectedResponse(binding, "prompt", workspaceHash(prompt))
	if result == nil || result.State != "failed" || result.ErrorCode != "CLAUDE_API_REQUEST_FAILED" || len(digest) != 64 {
		t.Fatalf("rejection proof: %+v %q", result, digest)
	}
}

func TestClaudeRejectionRejectsUncertainOrActiveEvidence(t *testing.T) {
	for _, mode := range []string{"prior user", "prior assistant", "prior compaction", "wrong prompt", "wrong hash", "foreign provider", "foreign assistant", "foreign end", "wrong cwd", "sidechain", "normal response", "not api error", "tool flag absent", "tool flag false", "server error", "input tokens", "output tokens", "missing usage", "tool block", "earlier reply", "tool result", "later user", "missing end", "wrong end parent", "missing error id", "past end", "future error", "retry after end", "unknown attachment", "malformed", "writable", "symlink", "ambiguous", "oversize"} {
		t.Run(mode, func(t *testing.T) {
			binding, path, _, prompt := reportFixture(t)
			records := claudeFailureRecords(binding, prompt, "prompt")
			message := records[1]["message"].(map[string]any)
			hash := workspaceHash(prompt)
			switch mode {
			case "prior user":
				records = append([]map[string]any{{"type": "user", "promptId": "earlier"}}, records...)
			case "prior assistant":
				records = append([]map[string]any{{"type": "assistant"}}, records...)
			case "prior compaction":
				records = append([]map[string]any{{"type": "system", "subtype": "compact_boundary"}}, records...)
			case "wrong prompt":
				records[0]["promptId"] = "foreign"
			case "wrong hash":
				hash = workspaceHash("another request")
			case "foreign provider":
				records[0]["sessionId"] = "foreign"
			case "foreign assistant":
				records[1]["sessionId"] = "foreign"
			case "foreign end":
				records[2]["sessionId"] = "foreign"
			case "wrong cwd":
				records[1]["cwd"] = t.TempDir()
			case "sidechain":
				records[1]["isSidechain"] = true
			case "normal response":
				message["model"] = "real-model"
			case "not api error":
				records[1]["isApiErrorMessage"] = false
			case "tool flag absent":
				delete(records[1], "failedResponseHadNoToolCall")
			case "tool flag false":
				records[1]["failedResponseHadNoToolCall"] = false
			case "server error":
				records[1]["apiErrorStatus"] = 500
			case "input tokens":
				message["usage"].(map[string]any)["input_tokens"] = 1
			case "output tokens":
				message["usage"].(map[string]any)["output_tokens"] = 1
			case "missing usage":
				delete(message, "usage")
			case "tool block":
				message["content"] = []any{map[string]any{"type": "tool_use", "id": "tool"}}
			case "earlier reply":
				records = append(records[:1], append([]map[string]any{{"type": "assistant", "message": map[string]any{"content": []any{map[string]any{"type": "text", "text": "Working"}}}}}, records[1:]...)...)
			case "tool result":
				records = append(records[:1], append([]map[string]any{{"type": "user", "message": map[string]any{"content": []any{map[string]any{"type": "tool_result"}}}}}, records[1:]...)...)
			case "later user":
				records = append(records, map[string]any{"type": "user", "promptId": "next", "message": map[string]any{"content": "next"}})
			case "missing end":
				records = records[:2]
			case "wrong end parent":
				records[2]["parentUuid"] = "foreign-error"
			case "missing error id":
				delete(records[1], "uuid")
			case "past end":
				records[2]["timestamp"] = time.Now().Add(-time.Hour).Format(time.RFC3339Nano)
			case "future error":
				records[1]["timestamp"] = time.Now().Add(time.Hour).Format(time.RFC3339Nano)
			case "retry after end":
				records = append(records, map[string]any{"type": "api-request"})
			case "unknown attachment":
				records = append(records[:1], append([]map[string]any{{"type": "attachment", "attachment": map[string]any{"type": "async-task"}}}, records[1:]...)...)
			}
			writeReportRecords(t, path, records)
			switch mode {
			case "malformed":
				if err := os.WriteFile(path, []byte("{"), 0600); err != nil {
					t.Fatal(err)
				}
			case "writable":
				if err := os.Chmod(path, 0666); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				target := path + ".real"
				if err := os.Rename(path, target); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(target, path); err != nil {
					t.Fatal(err)
				}
			case "ambiguous":
				other := filepath.Join(filepath.Dir(filepath.Dir(path)), "other")
				if err := os.Mkdir(other, 0700); err != nil {
					t.Fatal(err)
				}
				writeReportRecords(t, filepath.Join(other, binding.ProviderID+".jsonl"), records)
			case "oversize":
				if err := os.Truncate(path, (64<<20)+1); err != nil {
					t.Fatal(err)
				}
			}
			if result, _ := claudeRejectedResponse(binding, "prompt", hash); result != nil {
				t.Fatalf("%s accepted: %+v", mode, result)
			}
		})
	}
}

func rejectedClaudeTask(t *testing.T) (Service, SessionBinding, Spec, string, []map[string]any) {
	t.Helper()
	s, binding := sessionFixture(t)
	home := t.TempDir()
	t.Setenv("CLAUDE_CONFIG_DIR", home)
	for _, event := range []SessionEvent{claudeEvent("UserPromptSubmit", "seed"), claudeEvent("Stop", "seed"), claudeEvent("Notification", "seed")} {
		event.ProviderID = reportProviderID
		event.Prompt = "manual seed"
		event.StopAssistant = "ready"
		event.NotificationType = "idle_prompt"
		if err := s.applySessionEvent("claude", binding, event); err != nil {
			t.Fatal(err)
		}
	}
	spec := Spec{Key: "claude-rejected", Executor: "claude", SessionID: binding.ID, Prompt: "Read evidence without publication", TimeoutSeconds: 120}
	receipt, err := s.Launch(context.Background(), spec)
	if err != nil {
		t.Fatal(err)
	}
	binding = *receipt.Binding
	prompt, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "prompt"))
	event := claudeEvent("UserPromptSubmit", "prompt")
	event.ProviderID = reportProviderID
	event.Prompt = string(prompt)
	if err := s.applySessionEvent("claude", binding, event); err != nil {
		t.Fatal(err)
	}
	failure := claudeEvent("StopFailure", "prompt")
	failure.ProviderID = reportProviderID
	if err := s.applySessionEvent("claude", binding, failure); err != nil {
		t.Fatal(err)
	}
	directory := filepath.Join(home, "projects", "workspace")
	if err := os.MkdirAll(directory, 0700); err != nil {
		t.Fatal(err)
	}
	return s, binding, spec, filepath.Join(directory, reportProviderID+".jsonl"), claudeFailureRecords(binding, string(prompt), "prompt")
}

func TestClaudeRejectionSettlesAndReusesOriginalProvider(t *testing.T) {
	for _, cancel := range []bool{false, true} {
		t.Run(map[bool]string{false: "failed", true: "cancelled"}[cancel], func(t *testing.T) {
			s, binding, spec, path, records := rejectedClaudeTask(t)
			if cancel {
				if _, err := s.Cancel(spec.Key); err != nil {
					t.Fatal(err)
				}
			}
			writeReportRecords(t, path, records)
			status, err := s.Status(spec.Key)
			want := "failed"
			if cancel {
				want = "cancelled"
			}
			if err != nil || status.State != want || status.Result == nil || status.Result.InputStopped == nil || !*status.Result.InputStopped || status.Result.OutcomeKnown == nil || !*status.Result.OutcomeKnown || len(status.Result.StopEvidence) != 64 || status.Binding.ProviderID != reportProviderID {
				t.Fatalf("status %+v %v", status, err)
			}
			again, err := s.Status(spec.Key)
			if err != nil || again.Result.FinishedMS != status.Result.FinishedMS {
				t.Fatal("receipt changed")
			}
			spec.Key = "claude-followup"
			spec.Prompt = "Continue after model repair"
			continued, err := s.Launch(context.Background(), spec)
			if err != nil || continued.Session != binding.ID || continued.Binding.ProviderID != reportProviderID {
				t.Fatalf("provider replaced: %+v %v", continued, err)
			}
			old, _ := s.Status("claude-rejected")
			if old.Result == nil || old.State != want {
				t.Fatal("old failure receipt lost")
			}
		})
	}
}

func TestClaudeRejectionRetainsUnknownWithPendingWork(t *testing.T) {
	for _, mode := range []string{"tool", "process"} {
		t.Run(mode, func(t *testing.T) {
			s, binding, spec, path, records := rejectedClaudeTask(t)
			writeReportRecords(t, path, records)
			if mode == "tool" {
				file, _ := s.lifecycleFile(binding)
				var state sessionLifecycle
				if err := readJSON(file, &state); err != nil {
					t.Fatal(err)
				}
				state.Tools["pending"] = true
				if err := writeJSON(file, state); err != nil {
					t.Fatal(err)
				}
			} else {
				command := exec.Command("sleep", "30")
				if err := command.Start(); err != nil {
					t.Fatal(err)
				}
				defer func() { _ = command.Process.Kill(); _ = command.Wait() }()
			}
			status, err := s.Status(spec.Key)
			if err != nil || status.Result != nil || status.State != "unknown" {
				t.Fatalf("pending work settled: %+v %v", status, err)
			}
		})
	}
}
