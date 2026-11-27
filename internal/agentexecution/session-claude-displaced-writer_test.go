package agentexecution

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestDisplacedClaudeWriterRequiresLaterRefusalAndRetainsUnknownOutcome(t *testing.T) {
	for _, scenario := range []string{"stopped", "without cancel", "earlier refusal", "managed input", "later input", "unpaired queue", "successful response", "foreign parent", "pending tool"} {
		t.Run(scenario, func(t *testing.T) {
			svc, binding, spec, transcript, _ := rejectedClaudeTask(t)
			dir, _ := svc.directory(spec.Key)
			path, _ := svc.lifecycleFile(binding)
			var receipt Receipt
			if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
				t.Fatal(err)
			}
			var state sessionLifecycle
			if err := readJSON(path, &state); err != nil {
				t.Fatal(err)
			}
			state.Model, state.State, state.UnknownReason = "free", "unknown", "SESSION_PROMPT_MISMATCH"
			state.TurnID, state.PromptHash = "prior", workspaceHash("an earlier settled turn")
			spec.Persistent, spec.TimeoutSeconds, spec.PreparedFrom = true, 0, "prepared-main"
			receipt.DeadlineMS = 0
			initialDir, _ := svc.directory(spec.PreparedFrom)
			if err := os.MkdirAll(initialDir, 0700); err != nil {
				t.Fatal(err)
			}
			yes := true
			for file, value := range map[string]any{
				"spec.json":    Spec{Key: spec.PreparedFrom, Executor: "claude", Model: state.Model, Persistent: true},
				"receipt.json": receipt,
				"result.json":  Result{State: "succeeded", InputStopped: &yes, OutcomeKnown: &yes},
			} {
				if err := writeJSON(filepath.Join(initialDir, file), value); err != nil {
					t.Fatal(err)
				}
			}
			for file, value := range map[string]any{"spec.json": spec, "receipt.json": receipt, path: state} {
				if !filepath.IsAbs(file) {
					file = filepath.Join(dir, file)
				}
				if err := writeJSON(file, value); err != nil {
					t.Fatal(err)
				}
			}
			since := time.Now().Add(-time.Second).Truncate(time.Millisecond)
			if err := os.Chtimes(filepath.Join(dir, "spec.json"), since, since); err != nil {
				t.Fatal(err)
			}
			if scenario != "without cancel" {
				cancel := filepath.Join(dir, "cancel.json")
				if err := writeJSON(cancel, map[string]bool{"cancel": true}); err != nil {
					t.Fatal(err)
				}
				stamp := since.Add(10 * time.Millisecond)
				if scenario == "earlier refusal" {
					stamp = since.Add(300 * time.Millisecond)
				}
				if err := os.Chtimes(cancel, stamp, stamp); err != nil {
					t.Fatal(err)
				}
			}

			stamp := func(ms int) string {
				return since.Add(time.Duration(ms) * time.Millisecond).UTC().Format(time.RFC3339Nano)
			}
			record := func(kind, id, parent string, ms int) map[string]any {
				return map[string]any{"type": kind, "uuid": id, "parentUuid": parent,
					"timestamp": stamp(ms), "sessionId": binding.ProviderID, "cwd": binding.Directory}
			}
			direct := record("user", "direct", "", 100)
			direct["promptId"] = "direct"
			direct["message"] = map[string]any{"content": "try the selected gateway route"}
			date := record("attachment", "date", "direct", 101)
			date["attachment"] = map[string]string{"type": "date"}
			refusal := record("assistant", "refusal", "date", 200)
			refusal["isApiErrorMessage"], refusal["error"] = true, "invalid_request"
			refusal["message"] = map[string]any{"model": "<synthetic>", "role": "assistant",
				"stop_reason": "stop_sequence", "usage": map[string]int{"input_tokens": 0, "output_tokens": 0},
				"content": []any{map[string]any{"type": "text", "text": `Prompt is too long · automatic compaction failed: API Error: 503 {"error":{"code":"MODEL_ROUTE_NO_AVAILABLE_MEMBER"}}`}}}
			records := []map[string]any{direct, date, refusal}
			switch scenario {
			case "managed input":
				direct["message"] = map[string]any{"content": sessionPrompt(dir, spec)}
			case "later input":
				next := record("user", "next", "refusal", 240)
				next["promptId"], next["message"] = "next", map[string]any{"content": "other activity"}
				records = append(records, next)
			case "unpaired queue":
				records = []map[string]any{direct, {"type": "queue-operation", "operation": "enqueue", "timestamp": stamp(105)}, date, refusal}
			case "successful response":
				refusal["isApiErrorMessage"] = false
			case "foreign parent":
				refusal["parentUuid"] = "unrelated"
			case "pending tool":
				state.Tools = map[string]bool{"pending": true}
				if err := writeJSON(path, state); err != nil {
					t.Fatal(err)
				}
			}
			writeReportRecords(t, transcript, records)
			status, err := svc.ReconcileSession(context.Background(), spec.Key)
			if scenario != "stopped" {
				if err == nil || status.Result != nil {
					t.Fatalf("displaced execution unexpectedly settled: %+v, %v", status, err)
				}
				if _, err := os.Stat(filepath.Join(dir, "result.json")); !os.IsNotExist(err) {
					t.Fatalf("unexpected result on disk: %v", err)
				}
				return
			}
			result := status.Result
			if err != nil || result == nil || result.State != "cancelled" || result.ErrorCode != claudeStoppedUnknown ||
				result.InputStopped == nil || !*result.InputStopped || result.OutcomeKnown == nil || *result.OutcomeKnown ||
				!nativeEvidenceDigest.MatchString(result.StopEvidence) {
				t.Fatalf("wrong settlement: %+v, %v", result, err)
			}
			release, err := svc.claimWorkspace(context.Background(), binding.Directory, "next-owner")
			if err != nil {
				t.Fatalf("proved stopped writer still holds directory: %v", err)
			}
			release()
		})
	}
}
