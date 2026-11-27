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

func TestLongClaudeSubmitPreservesPromptAndBoundsOtherMetadata(t *testing.T) {
	prompt := strings.Repeat("原 Main 上下文\n", 16000)
	raw, _ := json.Marshal(map[string]any{"hook_event_name": "UserPromptSubmit", "session_id": "provider", "prompt_id": "turn", "prompt": prompt})
	event, err := ReadSessionEvent(strings.NewReader(string(raw)))
	if err != nil || event.Prompt != prompt {
		t.Fatalf("long input lost: %v", err)
	}
	for _, value := range []map[string]any{
		{"hook_event_name": "UserPromptSubmit", "prompt": strings.Repeat("x", (8<<20)+1)},
		{"hook_event_name": "UserPromptSubmit", "prompt": prompt, "tool_use_id": strings.Repeat("x", 100001)},
		{"hook_event_name": "PostToolUse", "prompt": prompt},
	} {
		data, _ := json.Marshal(value)
		if _, err := ReadSessionEvent(strings.NewReader(string(data))); err == nil {
			t.Fatal("unbounded metadata accepted")
		}
	}
}

func TestMissedLongSubmitRequiresOwnedInputCompleteStopAndOriginalProvider(t *testing.T) {
	for _, scenario := range []string{"complete", "wrapped trailing newline", "pasted mismatch", "pasted old input", "pasted invalid deadline", "cancelled", "missing hook failure", "wrong hook parent", "wrong hook error", "missing result", "wrong input", "wrong provider", "blocked stop", "later input", "async tool", "live process", "other writer", "unseen tool", "changed reason", "changed model"} {
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
			spec.Prompt = strings.Repeat("Original Main context\n", 8000)
			spec.TimeoutSeconds = 0
			spec.PreparedFrom = "prepared-long-main"
			initialDir, _ := s.directory(spec.PreparedFrom)
			if err := os.MkdirAll(initialDir, 0700); err != nil {
				t.Fatal(err)
			}
			yes := true
			initial := Spec{Key: spec.PreparedFrom, Executor: "claude", Model: state.Model, Persistent: true}
			for name, value := range map[string]any{"spec.json": initial, "receipt.json": receipt, "result.json": Result{State: "succeeded", InputStopped: &yes, OutcomeKnown: &yes}} {
				if err := writeJSON(filepath.Join(initialDir, name), value); err != nil {
					t.Fatal(err)
				}
			}
			if err := writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
				t.Fatal(err)
			}
			since := time.Now().Add(-time.Second).UnixMilli()
			stamp := time.UnixMilli(since)
			if err := os.Chtimes(filepath.Join(dir, "spec.json"), stamp, stamp); err != nil {
				t.Fatal(err)
			}
			state.State, state.UnknownReason = "unknown", "SESSION_TOOL_EVENT_MISMATCH"
			if strings.HasPrefix(scenario, "pasted ") {
				state.UnknownReason = "SESSION_PROMPT_MISMATCH"
				if scenario != "pasted invalid deadline" {
					receipt.DeadlineMS = 0
				}
				if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
					t.Fatal(err)
				}
			}
			state.TurnID, state.PromptHash = "previous-turn", workspaceHash("previous input")
			state.Tools = map[string]bool{}
			records := claudeDeniedCompletionTrace(binding, sessionPrompt(dir, spec), since)
			failure := map[string]any{"type": "attachment", "uuid": "submit-error", "parentUuid": "owned-user", "sessionId": binding.ProviderID, "cwd": binding.Directory, "timestamp": time.UnixMilli(since + 1).UTC().Format(time.RFC3339Nano), "attachment": map[string]any{"type": "hook_non_blocking_error", "hookName": "UserPromptSubmit", "hookEvent": "UserPromptSubmit", "exitCode": 1, "stderr": "Failed with non-blocking status code: INVALID_SESSION_EVENT"}}
			switch scenario {
			case "pasted mismatch", "pasted old input", "pasted invalid deadline":
				records[0]["message"] = map[string]any{"content": "\n\n<pasted_content id=\"transport\">\n" + sessionPrompt(dir, spec) + "\n</pasted_content id=\"transport\">\n"}
				if scenario == "pasted old input" {
					records[0]["timestamp"] = time.UnixMilli(since - 1).UTC().Format(time.RFC3339Nano)
				}
			case "wrapped trailing newline":
				records[0]["message"] = map[string]any{"content": "\n\n<pasted_content id=\"transport\">\n" + strings.TrimSuffix(sessionPrompt(dir, spec), "\n") + "\n</pasted_content id=\"transport\">\n"}
			case "cancelled":
				if err := writeJSON(filepath.Join(dir, "cancel.json"), map[string]bool{"requested": true}); err != nil {
					t.Fatal(err)
				}
			case "wrong hook parent":
				failure["parentUuid"] = "unrelated"
			case "wrong hook error":
				failure["attachment"].(map[string]any)["stderr"] = "other error"
			case "missing result":
				records = append(records[:2], records[3:]...)
			case "wrong input":
				records[0]["message"] = map[string]any{"content": "different input"}
			case "wrong provider":
				records[2]["sessionId"] = "foreign"
			case "blocked stop":
				records[4]["preventedContinuation"] = true
			case "later input":
				records = append(records, map[string]any{"type": "user", "uuid": "later", "sessionId": binding.ProviderID, "promptId": "new", "cwd": binding.Directory, "message": map[string]any{"content": "new request"}})
			case "async tool":
				records[1]["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_use", "id": "denied-bash", "name": "Agent", "input": map[string]any{}}}}
			case "unseen tool":
				state.Tools["unpaired"] = true
			case "changed reason":
				state.UnknownReason = "SESSION_PROMPT_MISMATCH"
			case "changed model":
				state.Model = "other"
			case "other writer":
				root, release, err := s.lockWorkspaceWriter(context.Background(), binding.Directory)
				if err != nil {
					t.Fatal(err)
				}
				err = writeJSON(filepath.Join(root, "writer.json"), map[string]string{"key": "different"})
				release()
				if err != nil {
					t.Fatal(err)
				}
			}
			if scenario != "missing hook failure" && !strings.HasPrefix(scenario, "pasted ") {
				records = append(records[:1], append([]map[string]any{failure}, records[1:]...)...)
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
			if scenario != "complete" && scenario != "wrapped trailing newline" && scenario != "pasted mismatch" && scenario != "cancelled" {
				if err == nil || result.Result != nil {
					t.Fatalf("unconfirmed %s accepted: %+v %v", scenario, result, err)
				}
				var after sessionLifecycle
				if readJSON(path, &after) != nil || after.State != "unknown" {
					t.Fatal("uncertain state changed")
				}
				return
			}
			want := "succeeded"
			if scenario == "cancelled" {
				want = "cancelled"
			}
			if err != nil || result.Result == nil || result.State != want || result.Result.InputStopped == nil || !*result.Result.InputStopped || result.Result.OutcomeKnown == nil || !*result.Result.OutcomeKnown || len(result.Result.StopEvidence) != 64 {
				t.Fatalf("missing actual proof: %+v %v", result, err)
			}
			var after sessionLifecycle
			if readJSON(path, &after) != nil || after.State != "idle" || after.Binding.ProviderID != binding.ProviderID || after.TurnID != "prompt" || after.PromptHash != workspaceHash(sessionPrompt(dir, spec)) {
				t.Fatal("original input/provider not retained")
			}
		})
	}
}
