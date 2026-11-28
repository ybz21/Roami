package agentexecution

import (
	"strings"
	"testing"
	"time"
)

func TestWrappedClaudeCompletionRequiresUnblockedStopAndAllToolResults(t *testing.T) {
	for _, scenario := range []string{"complete", "missing tool result", "blocked stop", "missing stop fields", "new request", "async tool", "wrong input"} {
		t.Run(scenario, func(t *testing.T) {
			binding, path, _, _ := reportFixture(t)
			raw := "owned task"
			payload := "\n\n<pasted_content id=\"84f2\">\n" + raw + "\n</pasted_content id=\"84f2\">\n"
			if scenario == "wrong input" {
				payload += "extra"
			}
			since := time.Now().Add(-10 * time.Second).UnixMilli()
			stamp := func(ms int64) string { return time.UnixMilli(since + ms).UTC().Format(time.RFC3339Nano) }
			r := func(kind, id, parent string, ms int64) map[string]any {
				return map[string]any{"type": kind, "uuid": id, "parentUuid": parent, "sessionId": binding.ProviderID, "cwd": binding.Directory, "timestamp": stamp(ms)}
			}
			user := r("user", "u1", "", 1000)
			user["promptId"] = "owned"
			user["message"] = map[string]any{"content": payload}
			tool := r("assistant", "a1", "u1", 2000)
			name := "Read"
			if scenario == "async tool" {
				name = "Agent"
			}
			tool["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_use", "id": "read-1", "name": name, "input": map[string]any{}}}}
			output := r("user", "u2", "a1", 3000)
			output["promptId"] = "owned"
			output["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_result", "tool_use_id": "read-1", "content": "actual file"}}}
			final := r("assistant", "a2", "u2", 4000)
			final["message"] = map[string]any{"stop_reason": "end_turn", "content": []any{map[string]any{"type": "text", "text": "Draft retained"}}}
			stop := r("system", "s1", "a2", 5000)
			stop["subtype"] = "stop_hook_summary"
			stop["session_id"] = binding.ProviderID
			stop["preventedContinuation"] = scenario == "blocked stop"
			stop["hookErrors"] = []any{}
			stop["failedHookErrorIndexes"] = []any{}
			stop["hookAdditionalContext"] = []any{}
			if scenario == "missing stop fields" {
				delete(stop, "hookErrors")
			}
			rows := []map[string]any{user, tool, output, final, stop}
			if scenario == "missing tool result" {
				rows = []map[string]any{user, tool, final, stop}
			}
			if scenario == "new request" {
				next := r("user", "u3", "s1", 6000)
				next["promptId"] = "foreign"
				next["message"] = map[string]any{"content": "new work"}
				rows = append(rows, next)
			}
			writeReportRecords(t, path, rows)
			result, _, _ := claudeCompletedEvidence(binding, "owned", workspaceHash(raw), since)
			if scenario == "complete" {
				if result == nil || result.State != "succeeded" || result.Summary != "Draft retained" {
					t.Fatal("missing actual completion", result)
				}
			} else if result != nil {
				t.Fatal("unconfirmed completion accepted", scenario)
			}
		})
	}
}

func TestClaudeGatewayRefusalAfterToolsPreservesKnownPartialOutcome(t *testing.T) {
	for _, scenario := range []string{"settled tools", "pending tool", "foreign provider", "new request", "untyped refusal", "settled HTTP 400", "HTTP 400 without tool marker", "HTTP 400 reported new tools", "HTTP 400 untyped", "HTTP 400 pending tool"} {
		t.Run(scenario, func(t *testing.T) {
			binding, path, launch, _ := reportFixture(t)
			since := time.Now().Add(-10 * time.Second).UnixMilli()
			row := func(kind, id, parent string, ms int64) map[string]any {
				return map[string]any{
					"type": kind, "uuid": id, "parentUuid": parent, "sessionId": binding.ProviderID, "cwd": binding.Directory,
					"timestamp": time.UnixMilli(since + ms).UTC().Format(time.RFC3339Nano),
				}
			}
			user := row("user", "input", "", 1000)
			user["promptId"], user["message"] = "owned", map[string]any{"content": "owned task"}
			tool := row("assistant", "call", "input", 2000)
			tool["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_use", "id": "bash-1", "name": "Bash"}}}
			output := row("user", "output", "call", 3000)
			output["promptId"] = "owned"
			output["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_result", "tool_use_id": "bash-1", "is_error": true}}}
			failure := row("assistant", "refusal", "output", 4000)
			failure["isApiErrorMessage"], failure["failedResponseHadNoToolCall"] = true, true
			failure["apiErrorStatus"], failure["error"] = 503, "server_error"
			failure["message"] = map[string]any{
				"model": "<synthetic>", "role": "assistant", "stop_reason": "stop_sequence",
				"usage":   map[string]int{"input_tokens": 0, "output_tokens": 0},
				"content": []any{map[string]any{"type": "text", "text": `API Error: 503 {"error":{"code":"MODEL_ROUTE_NO_AVAILABLE_MEMBER"}}`}},
			}
			rows := []map[string]any{user, tool, output, failure}
			expected := "MODEL_ROUTE_NO_AVAILABLE_MEMBER"
			if strings.Contains(scenario, "HTTP 400") {
				expected = "MODEL_HTTP_400"
				failure["apiErrorStatus"], failure["apiErrorType"], failure["error"] = 400, "api_error", "unknown"
				failure["message"].(map[string]any)["content"] = []any{map[string]any{"type": "text", "text": "API Error: 400 MODEL_HTTP_400"}}
			}
			switch scenario {
			case "pending tool", "HTTP 400 pending tool":
				failure["parentUuid"] = "call"
				rows = []map[string]any{user, tool, failure}
			case "foreign provider":
				failure["sessionId"] = "foreign"
			case "new request":
				later := row("user", "next", "refusal", 5000)
				later["promptId"], later["message"] = "later", map[string]any{"content": "new work"}
				rows = append(rows, later)
			case "untyped refusal", "HTTP 400 reported new tools":
				failure["failedResponseHadNoToolCall"] = false
			case "HTTP 400 without tool marker":
				delete(failure, "failedResponseHadNoToolCall")
			case "HTTP 400 untyped":
				delete(failure, "apiErrorType")
			}
			writeReportRecords(t, path, rows)
			result, digest, completed := claudeTerminalEvidence(binding, "owned", workspaceHash("owned task"), since, "", true)
			if scenario != "settled tools" && scenario != "settled HTTP 400" {
				if result != nil {
					t.Fatalf("unsafe partial outcome accepted: %+v", result)
				}
				return
			}
			if result == nil || result.State != "failed" || result.ErrorCode != "CLAUDE_MODEL_REQUEST_FAILED_AFTER_TOOLS" || result.Summary != expected || len(digest) != 64 || completed["bash-1"] == 0 {
				t.Fatalf("missing partial failure and tool proof: %+v", result)
			}
			if result, _, _ := claudeCompletedEvidence(binding, "owned", workspaceHash("owned task"), since); result != nil {
				t.Fatal("partial failure treated as success")
			}
			result.StopEvidence = digest
			state := sessionLifecycle{Binding: binding, TurnID: "owned", PromptHash: workspaceHash("owned task"), EndedIdle: true}
			script := Spec{TimeoutSeconds: 90}
			receipt := Receipt{DeadlineMS: since + 90000}
			rows = append(rows, map[string]any{"type": "last-prompt"})
			for _, recovery := range []string{"passive exit history", "no idle proof", "changed digest", "changed refusal", "changed time", "new work"} {
				t.Run(recovery, func(t *testing.T) {
					current, saved := state, *result
					history := rows
					switch recovery {
					case "no idle proof":
						current.EndedIdle = false
					case "changed digest":
						saved.StopEvidence = strings.Repeat("a", 64)
					case "changed refusal":
						saved.Summary = "another refusal"
					case "changed time":
						saved.FinishedMS++
					case "new work":
						history = append(history, row("user", "late-request", "refusal", 5000))
					}
					writeReportRecords(t, path, history)
					if got := claudeToolFailureRecoveryProven(current, launch, script, receipt, saved); got != (recovery == "passive exit history") {
						t.Fatalf("partial recovery accepted=%v", got)
					}
				})
			}
		})
	}
}
