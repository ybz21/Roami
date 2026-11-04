package agentexecution

import "testing"

func TestCodexAbortRequiresCancellationAndExactTerminalTurn(t *testing.T) {
	for _, mode := range []string{"valid", "no-cancellation", "missing-turn", "other-turn", "other-root", "wrong-prompt", "unfinished-call", "extra-input", "later-record"} {
		t.Run(mode, func(t *testing.T) {
			root := t.TempDir()
			t.Setenv("CODEX_HOME", root)
			binding := SessionBinding{ProviderID: completionThread, Directory: t.TempDir()}
			records := completionRecords(binding, "turn-1", "task prompt")[:5]
			payload := map[string]any{"type": "turn_aborted", "turn_id": "turn-1", "reason": "interrupted"}
			terminal := map[string]any{"type": "event_msg", "timestamp": "2026-11-04T01:55:26.363Z", "payload": payload}
			switch mode {
			case "missing-turn":
				delete(payload, "turn_id")
			case "other-turn":
				payload["turn_id"] = "other-turn"
			case "other-root":
				payload["root_turn_id"] = "other-turn"
			case "wrong-prompt":
				records[2]["payload"].(map[string]any)["content"] = []any{map[string]any{"type": "input_text", "text": "other prompt"}}
			case "unfinished-call":
				records = records[:4]
			case "extra-input":
				records = append(records, records[2])
			}
			records = append(records, terminal)
			if mode == "later-record" {
				records = append(records, map[string]any{"type": "event_msg", "payload": map[string]any{"type": "task_started", "turn_id": "other-turn"}})
			}
			saveCompletionRecords(t, root, records)
			result, proof := codexOutcome(binding, "turn-1", workspaceHash("task prompt"), mode != "no-cancellation")
			if mode == "valid" {
				if result == nil || result.State != "cancelled" || result.FinishedMS != 1793757326363 || len(proof) != 64 {
					t.Fatalf("abort not reconciled: %+v %q", result, proof)
				}
			} else if result != nil {
				t.Fatalf("unsafe abort %s: %+v", mode, result)
			}
			if result, _ := codexCompletion(binding, "turn-1", workspaceHash("task prompt")); result != nil {
				t.Fatal("abort became a successful completion")
			}
		})
	}
}
