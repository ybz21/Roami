package agentexecution

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestPreparedClaudeQuotaRefusalRequiresOwnedZeroWorkEvidence(t *testing.T) {
	for _, scenario := range []string{
		"complete", "gateway input rejected", "untyped 400", "wrong 400 code", "gateway rate limit",
		"untyped 429", "compaction refusal",
		"compaction input rejected", "unowned attachment", "route exhausted", "untyped 503",
		"wrong route code", "prior history", "owned child", "cancelled", "existing session",
		"nonpersistent", "changed model", "wrong hash", "wrong parent", "wrong provider", "stale input",
		"ordinary assistant", "not api error", "missing no-tool flag", "input usage", "output usage",
		"server error", "other quota", "real output before", "tool before", "later input", "later request",
		"escaping cwd", "pending tool", "live process", "other writer",
	} {
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
			case "gateway input rejected", "untyped 400", "wrong 400 code":
				records[1]["apiErrorStatus"] = 400
				records[1]["apiErrorType"] = "api_error"
				records[1]["error"] = "unknown"
				refusal := "API Error: 400 MODEL_HTTP_400"
				if scenario == "untyped 400" {
					delete(records[1], "apiErrorType")
				}
				if scenario == "wrong 400 code" {
					refusal = "API Error: 400 INVALID_REQUEST"
				}
				message["content"] = []any{map[string]any{"type": "text", "text": refusal}}
			case "gateway rate limit", "untyped 429":
				records[1]["apiErrorStatus"] = 429
				records[1]["apiErrorType"] = "api_error"
				records[1]["error"] = "rate_limit"
				refusal := "API Error: Request rejected (429) · MODEL_HTTP_429"
				if scenario == "untyped 429" {
					refusal = "API Error: 429 Unavailable"
				}
				message["content"] = []any{map[string]any{"type": "text", "text": refusal}}
			case "compaction input rejected", "unowned attachment":
				delete(records[1], "apiErrorStatus")
				delete(records[1], "failedResponseHadNoToolCall")
				records[1]["error"] = "invalid_request"
				message["content"] = []any{map[string]any{"type": "text", "text": "Prompt is too long · automatic compaction failed: API Error: 400 MODEL_HTTP_400"}}
				parent := "quota-user"
				if scenario == "unowned attachment" {
					parent = "unrelated"
				}
				attachment := map[string]any{"type": "attachment", "uuid": "date", "parentUuid": parent,
					"sessionId": binding.ProviderID, "cwd": binding.Directory, "attachment": map[string]string{"type": "date"}}
				records[1]["parentUuid"] = "date"
				records = []map[string]any{records[0], attachment, records[1]}
			case "compaction refusal":
				delete(records[1], "apiErrorStatus")
				delete(records[1], "failedResponseHadNoToolCall")
				records[1]["error"] = "invalid_request"
				message["content"] = []any{map[string]any{"type": "text", "text": `Prompt is too long · automatic compaction failed: API Error: 503 {"error":{"code":"MODEL_ROUTE_NO_AVAILABLE_MEMBER"}}. This is a server-side issue.`}}
			case "route exhausted", "untyped 503", "wrong route code":
				records[1]["apiErrorStatus"] = 503
				records[1]["error"] = "server_error"
				refusal := `API Error: 503 {"error":{"code":"MODEL_ROUTE_NO_AVAILABLE_MEMBER"}}. This is a server-side issue, usually temporary — try again in a moment.`
				if scenario == "untyped 503" {
					refusal = "API Error: 503 unavailable"
				}
				if scenario == "wrong route code" {
					refusal = strings.Replace(refusal, "MODEL_ROUTE_NO_AVAILABLE_MEMBER", "MODEL_ROUTE_UNAVAILABLE", 1)
				}
				message["content"] = []any{map[string]any{"type": "text", "text": refusal}}
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
			var code string
			switch scenario {
			case "complete", "existing session", "prior history", "owned child", "cancelled":
				code = "MODEL_PROXY_DAILY_LIMIT"
			case "gateway input rejected":
				code = "MODEL_HTTP_400"
			case "gateway rate limit":
				code = "MODEL_HTTP_429"
			case "compaction refusal":
				code = "CLAUDE_COMPACTION_FAILED"
			case "compaction input rejected":
				code = "CLAUDE_COMPACTION_INPUT_REJECTED"
			case "route exhausted":
				code = "MODEL_ROUTE_NO_AVAILABLE_MEMBER"
			}
			if code == "" {
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
			if err != nil || result.Result == nil || result.State != want || result.Result.ErrorCode != code || result.Result.InputStopped == nil || !*result.Result.InputStopped || result.Result.OutcomeKnown == nil || !*result.Result.OutcomeKnown || len(result.Result.StopEvidence) != 64 {
				t.Fatalf("rejection not preserved as known failure: %+v %v", result, err)
			}
			var after sessionLifecycle
			if err := readJSON(path, &after); err != nil || after.State != "idle" || after.Binding.ProviderID != binding.ProviderID {
				t.Fatal("original provider not retained")
			}
		})
	}
}

func TestClaudeCompactionRefusalRequiresTypedTerminalError(t *testing.T) {
	for _, scenario := range []string{"complete", "wrong code", "wrong status", "ordinary text", "wrong failure", "extra block", "invalid JSON"} {
		t.Run(scenario, func(t *testing.T) {
			r := claudeFailureRecord{Failure: "invalid_request"}
			text := `Prompt is too long · automatic compaction failed: API Error: 503 {"error":{"code":"MODEL_ROUTE_NO_AVAILABLE_MEMBER"}}. This is a server-side issue.`
			switch scenario {
			case "wrong code":
				text = strings.ReplaceAll(text, "MODEL_ROUTE_NO_AVAILABLE_MEMBER", "OTHER")
			case "wrong status":
				r.APIStatus = 503
			case "ordinary text":
				text = "API Error: 503 MODEL_ROUTE_NO_AVAILABLE_MEMBER"
			case "wrong failure":
				r.Failure = "other"
			case "invalid JSON":
				text = strings.ReplaceAll(text, `{"error":`, `{broken:`)
			}
			blocks := []map[string]string{{"type": "text", "text": text}}
			if scenario == "extra block" {
				blocks = append(blocks, map[string]string{"type": "tool_use"})
			}
			r.Message.Content, _ = json.Marshal(blocks)
			if claudeCompactionRefusal(r) != (scenario == "complete") {
				t.Fatal("unexpected refusal evidence", scenario)
			}
		})
	}
}
