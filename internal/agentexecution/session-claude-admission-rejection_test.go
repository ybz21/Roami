package agentexecution

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestPreparedClaudeQuotaRefusalRequiresOwnedZeroWorkEvidence(t *testing.T) {
	for _, scenario := range []string{"complete", "prior history", "owned child", "cancelled", "existing session", "nonpersistent", "changed model", "wrong hash", "wrong parent", "wrong provider", "stale input", "ordinary assistant", "not api error", "missing no-tool flag", "input usage", "output usage", "server error", "other quota", "real output before", "tool before", "later input", "later request", "escaping cwd", "pending tool", "live process", "other writer"} {
		t.Run(scenario, func(t *testing.T) {
			s, binding, spec, transcript, _ := rejectedClaudeTask(t)
			dir, _ := s.directory(spec.Key)
			var receipt Receipt
			if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
				t.Fatal(err)
			}
			path, _ := s.lifecycleFile(binding)
			var state sessionLifecycle
			if err := readJSON(path, &state); err != nil {
				t.Fatal(err)
			}
			state.Model = "free"
			spec.Model = "free"
			spec.Persistent = true
			spec.PreparedFrom = "prepared-quota-provider"
			spec.TimeoutSeconds = 0
			receipt.DeadlineMS = 0
			initialDir, _ := s.directory(spec.PreparedFrom)
			if err := os.MkdirAll(initialDir, 0700); err != nil {
				t.Fatal(err)
			}
			yes := true
			for name, value := range map[string]any{"spec.json": Spec{Key: spec.PreparedFrom, Executor: "claude", Model: "free", Persistent: true}, "receipt.json": receipt, "result.json": Result{State: "succeeded", InputStopped: &yes, OutcomeKnown: &yes}} {
				if err := writeJSON(filepath.Join(initialDir, name), value); err != nil {
					t.Fatal(err)
				}
			}
			if scenario == "existing session" {
				spec.PreparedFrom, spec.Model = "", ""
			}
			if scenario == "nonpersistent" {
				spec.Persistent = false
			}
			if err := writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
				t.Fatal(err)
			}
			if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
				t.Fatal(err)
			}
			since := time.Now().Add(-time.Second)
			if err := os.Chtimes(filepath.Join(dir, "spec.json"), since, since); err != nil {
				t.Fatal(err)
			}
			state.State, state.UnknownReason, state.LaunchKey = "unknown", "", spec.Key
			state.TurnID, state.PromptHash = "prompt", workspaceHash(sessionPrompt(dir, spec))
			state.Tools = map[string]bool{}
			records := claudeFailureRecords(binding, sessionPrompt(dir, spec), "prompt")[:2]
			records[0]["uuid"] = "quota-user"
			records[0]["timestamp"] = since.Add(time.Millisecond).UTC().Format(time.RFC3339Nano)
			records[1]["parentUuid"] = "quota-user"
			records[1]["timestamp"] = since.Add(2 * time.Millisecond).UTC().Format(time.RFC3339Nano)
			records[1]["apiErrorStatus"] = 402
			message := records[1]["message"].(map[string]any)
			message["content"] = []any{map[string]any{"type": "text", "text": "API Error: 402 {\"error\":{\"code\":\"MODEL_PROXY_DAILY_LIMIT\"}}"}}
			switch scenario {
			case "prior history":
				records = append([]map[string]any{{"type": "user", "promptId": "prior", "message": map[string]any{"content": "prior completed work"}}, {"type": "assistant", "message": map[string]any{"content": "prior result"}}}, records...)
			case "owned child":
				child := filepath.Join(binding.Directory, "materials")
				if err := os.Mkdir(child, 0700); err != nil {
					t.Fatal(err)
				}
				for _, r := range records {
					r["cwd"] = child
				}
			case "cancelled":
				if err := writeJSON(filepath.Join(dir, "cancel.json"), map[string]bool{"requested": true}); err != nil {
					t.Fatal(err)
				}
			case "changed model":
				state.Model = "different"
			case "wrong hash":
				state.PromptHash = workspaceHash("foreign input")
			case "wrong parent":
				records[1]["parentUuid"] = "foreign"
			case "wrong provider":
				records[1]["sessionId"] = "foreign"
			case "stale input":
				records[0]["timestamp"] = since.Add(-time.Second).UTC().Format(time.RFC3339Nano)
			case "ordinary assistant":
				message["model"] = "free"
			case "not api error":
				records[1]["isApiErrorMessage"] = false
			case "missing no-tool flag":
				delete(records[1], "failedResponseHadNoToolCall")
			case "input usage":
				message["usage"].(map[string]any)["input_tokens"] = 1
			case "output usage":
				message["usage"].(map[string]any)["output_tokens"] = 1
			case "server error":
				records[1]["apiErrorStatus"] = 500
			case "other quota":
				message["content"] = []any{map[string]any{"type": "text", "text": "API Error: 402 {\"error\":{\"code\":\"OTHER_LIMIT\"}}"}}
			case "real output before", "tool before":
				extra := map[string]any{"type": "assistant", "sessionId": binding.ProviderID, "cwd": binding.Directory, "message": map[string]any{"model": "free", "content": "partial answer"}}
				if scenario == "tool before" {
					extra["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_use", "id": "tool", "name": "Bash"}}}
				}
				records = append(records[:1], append([]map[string]any{extra}, records[1:]...)...)
			case "later input":
				records = append(records, map[string]any{"type": "user", "promptId": "later", "message": map[string]any{"content": "new work"}})
			case "later request":
				records = append(records, map[string]any{"type": "api-request"})
			case "escaping cwd":
				records[0]["cwd"] = t.TempDir()
			case "pending tool":
				state.Tools["pending"] = true
			case "other writer":
				root, release, err := s.lockWorkspaceWriter(context.Background(), binding.Directory)
				if err != nil {
					t.Fatal(err)
				}
				err = writeJSON(filepath.Join(root, "writer.json"), map[string]string{"key": "other"})
				release()
				if err != nil {
					t.Fatal(err)
				}
			}
			writeReportRecords(t, transcript, records)
			if err := writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			if scenario == "live process" {
				child := exec.Command("sleep", "30")
				if err := child.Start(); err != nil {
					t.Fatal(err)
				}
				defer func() { _ = child.Process.Kill(); _ = child.Wait() }()
			}
			result, err := s.ReconcileSession(context.Background(), spec.Key)
			good := scenario == "complete" || scenario == "existing session" || scenario == "prior history" || scenario == "owned child" || scenario == "cancelled"
			if !good {
				if err == nil || result.Result != nil {
					t.Fatalf("accepted %s: %+v %v", scenario, result, err)
				}
				if _, err := os.Stat(filepath.Join(dir, "result.json")); !os.IsNotExist(err) {
					t.Fatal("uncertain rejection changed outcome")
				}
				return
			}
			want := "failed"
			if scenario == "cancelled" {
				want = "cancelled"
			}
			if err != nil || result.Result == nil || result.State != want || result.Result.ErrorCode != "MODEL_PROXY_DAILY_LIMIT" || result.Result.InputStopped == nil || !*result.Result.InputStopped || result.Result.OutcomeKnown == nil || !*result.Result.OutcomeKnown || len(result.Result.StopEvidence) != 64 {
				t.Fatalf("quota not preserved as known failure: %+v %v", result, err)
			}
			var after sessionLifecycle
			if err := readJSON(path, &after); err != nil || after.State != "idle" || after.Binding.ProviderID != binding.ProviderID {
				t.Fatal("original provider not retained")
			}
		})
	}
}
