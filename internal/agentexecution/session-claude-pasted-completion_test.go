package agentexecution

import (
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
