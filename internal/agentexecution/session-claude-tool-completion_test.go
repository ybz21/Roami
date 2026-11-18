package agentexecution

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func claudeDeniedCompletionTrace(binding SessionBinding, prompt string, since int64) []map[string]any {
	record := func(kind, id, parent string, offset int64) map[string]any {
		return map[string]any{"type": kind, "uuid": id, "parentUuid": parent, "sessionId": binding.ProviderID, "cwd": binding.Directory, "timestamp": time.UnixMilli(since + offset).UTC().Format(time.RFC3339Nano)}
	}
	user := record("user", "owned-user", "", 1)
	user["promptId"] = "prompt"
	user["message"] = map[string]any{"content": prompt}
	tool := record("assistant", "owned-tool", "owned-user", 2)
	tool["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_use", "id": "denied-bash", "name": "Bash", "input": map[string]any{"command": "python3 collect.py"}}}}
	output := record("user", "owned-result", "owned-tool", 3)
	output["promptId"] = "prompt"
	output["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_result", "tool_use_id": "denied-bash", "is_error": true, "content": "Classifier unavailable; command did not execute"}}}
	final := record("assistant", "owned-final", "owned-result", 4)
	final["message"] = map[string]any{"stop_reason": "end_turn", "content": []any{map[string]any{"type": "text", "text": "No collection occurred; source data remain unknown"}}}
	stop := record("system", "owned-stop", "owned-final", 5)
	stop["subtype"] = "stop_hook_summary"
	stop["session_id"] = binding.ProviderID
	stop["preventedContinuation"] = false
	stop["hookErrors"] = []any{}
	stop["failedHookErrorIndexes"] = []any{}
	stop["hookAdditionalContext"] = []any{}
	return []map[string]any{user, tool, output, final, stop}
}

func TestClaudeMissingToolHookRequiresCompleteBoundTranscriptAndStoppedProcesses(t *testing.T) {
	for _, scenario := range []string{"complete", "cancelled", "missing result", "unseen pending tool", "wrong input", "wrong provider", "blocked stop", "later input", "async tool", "live process", "other writer", "changed reason"} {
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
			state.State, state.UnknownReason = "unknown", ""
			state.Tools = map[string]bool{"denied-bash": true}
			records := claudeDeniedCompletionTrace(binding, sessionPrompt(dir, spec), receipt.DeadlineMS-int64(spec.TimeoutSeconds)*1000)
			switch scenario {
			case "missing result":
				records = append(records[:2], records[3:]...)
			case "unseen pending tool":
				state.Tools["unseen"] = true
			case "wrong input":
				records[0]["message"] = map[string]any{"content": "different work"}
			case "wrong provider":
				records[2]["sessionId"] = "foreign"
			case "blocked stop":
				records[4]["preventedContinuation"] = true
			case "later input":
				records = append(records, map[string]any{"type": "user", "uuid": "later", "promptId": "later", "sessionId": binding.ProviderID, "cwd": binding.Directory, "message": map[string]any{"content": "new work"}})
			case "async tool":
				records[1]["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_use", "id": "denied-bash", "name": "Agent", "input": map[string]any{}}}}
			case "changed reason":
				state.UnknownReason = "SESSION_PROMPT_MISMATCH"
			case "other writer":
				root, release, err := s.lockWorkspaceWriter(context.Background(), binding.Directory)
				if err != nil {
					t.Fatal(err)
				}
				err = writeJSON(filepath.Join(root, "writer.json"), map[string]string{"key": "another-task"})
				release()
				if err != nil {
					t.Fatal(err)
				}
			case "cancelled":
				if err := writeJSON(filepath.Join(dir, "cancel.json"), map[string]bool{"requested": true}); err != nil {
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
			before, err := s.Status(spec.Key)
			if err != nil || before.Result != nil {
				t.Fatalf("implicit status settled pending hook: %+v %v", before, err)
			}
			result, err := s.ReconcileSession(context.Background(), spec.Key)
			if scenario != "complete" && scenario != "cancelled" {
				if err == nil || result.Result != nil {
					t.Fatalf("accepted %s: %+v %v", scenario, result, err)
				}
				var after sessionLifecycle
				if readJSON(path, &after) != nil || len(after.Tools) == 0 {
					t.Fatal("pending hook was discarded")
				}
				return
			}
			want := "succeeded"
			if scenario == "cancelled" {
				want = "cancelled"
			}
			if err != nil || result.Result == nil || result.State != want || result.Result.InputStopped == nil || !*result.Result.InputStopped || result.Result.OutcomeKnown == nil || !*result.Result.OutcomeKnown || len(result.Result.StopEvidence) != 64 || result.Result.Summary != "No collection occurred; source data remain unknown" {
				t.Fatalf("missing completion: %+v %v", result, err)
			}
			var after sessionLifecycle
			if readJSON(path, &after) != nil || len(after.Tools) != 0 || after.State != "idle" || after.CompletedKey != spec.Key || after.Binding.ProviderID != binding.ProviderID {
				t.Fatal("original provider was not retained")
			}
			saved, err := s.Status(spec.Key)
			if err != nil || saved.Result == nil || saved.Result.StopEvidence != result.Result.StopEvidence {
				t.Fatal("completion evidence changed")
			}
			if _, err := os.Stat(filepath.Join(dir, "result.json")); err != nil {
				t.Fatal(err)
			}
		})
	}
}
