package agentexecution

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestCodexUntrackedStopRequiresCurrentAuthenticatedTerminalHistory(t *testing.T) {
	for _, mode := range []string{"valid", "compacted", "later-turn", "wrong-prompt", "old-start", "wrong-provider", "wrong-directory", "wrong-root", "open-call", "later-record", "duplicate-assignment", "partial", "sidechain", "later-unterminated", "symlink", "writable", "ambiguous"} {
		t.Run(mode, func(t *testing.T) {
			root := t.TempDir()
			t.Setenv("CODEX_HOME", root)
			binding := SessionBinding{ProviderID: completionThread, Directory: t.TempDir()}
			records := completionRecords(binding, "new-turn", "current assignment")
			since, _ := time.Parse(time.RFC3339Nano, "2026-10-26T11:15:35Z")
			payload := func(i int) map[string]any { return records[i]["payload"].(map[string]any) }
			switch mode {
			case "compacted":
				records = append(records[:2], append([]map[string]any{{"type": "compacted", "payload": map[string]any{"message": "compressed previous history"}}}, records[2:]...)...)
			case "later-turn", "later-unterminated":
				more := completionRecords(binding, "followup-turn", "manual followup")[1:]
				if mode == "later-unterminated" {
					more = more[:2]
				}
				records = append(records, more...)
			case "wrong-prompt":
				payload(2)["content"] = []any{map[string]any{"type": "input_text", "text": "other assignment"}}
			case "old-start":
				since = since.Add(time.Second)
			case "wrong-provider":
				payload(0)["id"] = "foreign"
			case "wrong-directory":
				payload(0)["cwd"] = t.TempDir()
			case "wrong-root":
				payload(6)["root_turn_id"] = "foreign"
			case "open-call":
				records = append(records[:4], records[5:]...)
			case "later-record":
				records = append(records, map[string]any{"type": "event_msg", "payload": map[string]any{"type": "token_count"}})
			case "duplicate-assignment":
				records = append(records[:3], append([]map[string]any{records[2]}, records[3:]...)...)
			case "partial":
				records = records[:len(records)-1]
			case "sidechain":
				payload(1)["root_turn_id"] = "other-root"
			}
			file := saveCompletionRecords(t, root, records)
			switch mode {
			case "symlink":
				raw, err := os.ReadFile(file)
				if err != nil {
					t.Fatal(err)
				}
				target := filepath.Join(t.TempDir(), "transcript")
				if err := os.WriteFile(target, raw, 0600); err != nil {
					t.Fatal(err)
				}
				if err := os.Remove(file); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(target, file); err != nil {
					t.Fatal(err)
				}
			case "writable":
				if err := os.Chmod(file, 0666); err != nil {
					t.Fatal(err)
				}
			case "ambiguous":
				raw, err := os.ReadFile(file)
				if err != nil {
					t.Fatal(err)
				}
				other := filepath.Join(root, "sessions", "2026", "10", "25", filepath.Base(file))
				if err := os.MkdirAll(filepath.Dir(other), 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(other, raw, 0600); err != nil {
					t.Fatal(err)
				}
			}
			result, proof, _ := codexUntrackedStop(binding, workspaceHash("current assignment"), since.UnixMilli())
			valid := mode == "valid" || mode == "compacted" || mode == "later-turn"
			if valid {
				if result == nil || result.State != "failed" || result.Summary != "SESSION_SCOPE_CHANGED_STOPPED" || len(proof) != 64 {
					t.Fatalf("missing stop: %+v %s", result, proof)
				}
			} else if result != nil {
				t.Fatalf("unproven stop: %+v", result)
			}
		})
	}
}

func TestUntrackedCodexReconciliationPreservesMemberAndNeverReplaysInput(t *testing.T) {
	s, binding, spec, records := changedInputFixture(t)
	stamp := time.Now().UTC().Format(time.RFC3339Nano)
	for _, r := range records {
		r["timestamp"] = stamp
	}
	more := completionRecords(binding, "later-turn", "later manual instruction")[1:]
	for _, r := range more {
		r["timestamp"] = stamp
	}
	records = append(records, more...)
	saveCompletionRecords(t, os.Getenv("CODEX_HOME"), records)
	path, _ := s.lifecycleFile(binding)
	var state sessionLifecycle
	if err := readJSON(path, &state); err != nil {
		t.Fatal(err)
	}
	state.UnknownReason, state.TurnID, state.PromptHash = "SESSION_START_UNTRACKED", "old-turn", workspaceHash("old assignment")
	if err := writeJSON(path, state); err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
	result, err := s.ReconcileSession(context.Background(), spec.Key)
	if err != nil || result.State != "failed" || result.Result == nil || result.Result.InputStopped == nil || !*result.Result.InputStopped || result.Result.OutcomeKnown == nil || !*result.Result.OutcomeKnown {
		t.Fatalf("not reconciled: %+v %v", result, err)
	}
	if result.Binding.ProviderID != binding.ProviderID || result.Binding.Pane != binding.Pane {
		t.Fatal("original member changed")
	}
	after, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
	if string(before) != string(after) {
		t.Fatal("replayed input")
	}
	next := spec
	next.Key = "continue-original"
	next.Prompt = "Reconcile publication, do not resend"
	resumed, err := s.Launch(context.Background(), next)
	if err != nil || resumed.Binding == nil || resumed.Binding.ProviderID != binding.ProviderID {
		t.Fatalf("cannot continue original: %+v %v", resumed, err)
	}
}

func TestStatusAutomaticallySettlesOnlyProvenUntrackedCodexLaunch(t *testing.T) {
	for _, mode := range []string{"valid", "cancelled", "wrong-prompt", "pending-tool", "foreign-hook", "other-spec", "old-transcript"} {
		t.Run(mode, func(t *testing.T) {
			s, binding, spec, records := changedInputFixture(t)
			stamp := time.Now().UTC().Format(time.RFC3339Nano)
			if mode != "old-transcript" {
				for _, r := range records {
					r["timestamp"] = stamp
				}
			}
			if mode == "wrong-prompt" {
				records[2]["payload"].(map[string]any)["content"] = []any{map[string]any{"type": "input_text", "text": "unrelated task"}}
			}
			saveCompletionRecords(t, os.Getenv("CODEX_HOME"), records)
			path, _ := s.lifecycleFile(binding)
			var state sessionLifecycle
			if err := readJSON(path, &state); err != nil {
				t.Fatal(err)
			}
			state.UnknownReason, state.TurnID, state.PromptHash = "SESSION_START_UNTRACKED", "stale-turn", workspaceHash("stale-prompt")
			switch mode {
			case "pending-tool":
				state.Tools["pending"] = true
			case "foreign-hook":
				state.ProviderConflict = &sessionProviderConflict{Executor: "codex", Hook: "PreToolUse", ProviderID: "foreign"}
			case "other-spec":
				spec.SessionID = "other-session"
				dir, _ := s.directory(spec.Key)
				if err := writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
					t.Fatal(err)
				}
			}
			if err := writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			if mode == "cancelled" {
				dir, _ := s.directory(spec.Key)
				if err := os.WriteFile(filepath.Join(dir, "cancel.json"), []byte("{}"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			before, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
			status, err := s.Status(spec.Key)
			if err != nil {
				t.Fatal(err)
			}
			if mode == "valid" || mode == "cancelled" {
				expected := "failed"
				if mode == "cancelled" {
					expected = "cancelled"
				}
				if status.State != expected || status.Result == nil || status.Result.InputStopped == nil || !*status.Result.InputStopped || status.Result.OutcomeKnown == nil || !*status.Result.OutcomeKnown || len(status.Result.StopEvidence) != 64 {
					t.Fatalf("no automatic stop: %+v", status)
				}
				dir, _ := s.directory(spec.Key)
				var proof completionSource
				if err := readJSON(filepath.Join(dir, "completion-source.json"), &proof); err != nil || proof.TurnID != "" {
					t.Fatalf("stale turn claimed: %+v %v", proof, err)
				}
			} else if status.State != "unknown" || status.Result != nil {
				t.Fatalf("unproven stop: %+v", status)
			}
			after, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
			if string(after) != string(before) {
				t.Fatal("replayed input")
			}
		})
	}
}
