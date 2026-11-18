package agentexecution

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestClaudeLocalCompactionDoesNotHideExecution(t *testing.T) {
	prefix := []byte("{\"type\":\"assistant\",\"message\":{\"content\":\"previous stopped turn\"}}\n")
	digest := sha256.Sum256(prefix)
	proof := hex.EncodeToString(digest[:])
	user := func(text string) map[string]any {
		return map[string]any{"type": "user", "sessionId": "provider", "cwd": "/project", "promptId": "compact", "message": map[string]any{"content": text}}
	}
	summary := user("retained summary")
	summary["isCompactSummary"] = true
	summary["isVisibleInTranscriptOnly"] = true
	caveat := user(claudeLocalCommandCaveat)
	caveat["isMeta"] = true
	records := []map[string]any{
		{"type": "system", "subtype": "compact_boundary", "sessionId": "provider", "cwd": "/project"},
		summary, caveat,
		user("<command-name>/compact</command-name>\n<command-message>compact</command-message>\n<command-args>retain memory</command-args>"),
		user("<local-command-stdout>\x1b[2mCompacted (ctrl+o to see full summary)\x1b[22m</local-command-stdout>"),
		{"type": "cost-state", "sessionId": "provider"},
	}
	encode := func(values []map[string]any) []byte {
		data := append([]byte{}, prefix...)
		for _, record := range values {
			b, err := json.Marshal(record)
			if err != nil {
				t.Fatal(err)
			}
			data = append(data, b...)
			data = append(data, '\n')
		}
		return data
	}
	if !claudeOnlyLocalCompaction(encode(records), proof, "provider", "/project") {
		t.Fatal("local compaction rejected")
	}
	for _, tc := range []struct {
		name   string
		record map[string]any
	}{
		{"assistant", map[string]any{"type": "assistant", "sessionId": "provider", "message": map[string]any{"content": "new execution"}}},
		{"user request", user("execute delegated task")},
		{"tool result", map[string]any{"type": "user", "sessionId": "provider", "cwd": "/project", "promptId": "compact", "message": map[string]any{"content": []any{map[string]any{"type": "tool_result", "tool_use_id": "new"}}}}},
		{"progress", map[string]any{"type": "progress"}},
		{"foreign provider", map[string]any{"type": "cost-state", "sessionId": "foreign"}},
		{"foreign directory", map[string]any{"type": "cost-state", "cwd": "/other"}},
		{"unknown attachment", map[string]any{"type": "attachment", "attachment": map[string]any{"type": "task_result"}}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			changed := append(append([]map[string]any{}, records...), tc.record)
			if claudeOnlyLocalCompaction(encode(changed), proof, "provider", "/project") {
				t.Fatal("new activity accepted")
			}
		})
	}
	data := encode(records)
	for name, changed := range map[string][]byte{"modified prefix": append([]byte(" "), data...), "partial JSON": append(data, []byte("{")...), "missing stdout": encode(records[:4]), "no compaction": prefix} {
		t.Run(name, func(t *testing.T) {
			if claudeOnlyLocalCompaction(changed, proof, "provider", "/project") {
				t.Fatal("incomplete evidence accepted")
			}
		})
	}
}

func TestMissingClaudeCompactionReconcilesOnlyUnsubmittedContinuation(t *testing.T) {
	for _, invalid := range []string{"", "executed", "changed prefix", "no prior stop", "current prompt", "wrong binding"} {
		t.Run(invalid, func(t *testing.T) {
			s, spec, receipt, transcript := missingClaudeRejection(t)
			dir, _ := s.directory(spec.Key)
			old := spec
			old.Key = "previous-stopped-turn"
			oldDir, _ := s.directory(old.Key)
			if err := os.MkdirAll(oldDir, 0700); err != nil {
				t.Fatal(err)
			}
			prefix, err := os.ReadFile(transcript)
			if err != nil {
				t.Fatal(err)
			}
			digest := sha256.Sum256(prefix)
			yes := true
			priorResult := Result{State: "failed", ErrorCode: "CLAUDE_SESSION_INTERRUPTED", InputStopped: &yes, OutcomeKnown: &yes, StopEvidence: hex.EncodeToString(digest[:])}
			if invalid == "no prior stop" {
				priorResult.InputStopped = nil
			}
			previous := receipt
			if invalid == "wrong binding" {
				b := *previous.Binding
				b.ProviderID = "other"
				previous.Binding = &b
			}
			for path, value := range map[string]any{filepath.Join(oldDir, "spec.json"): old, filepath.Join(oldDir, "receipt.json"): previous, filepath.Join(oldDir, "result.json"): priorResult} {
				if err := writeJSON(path, value); err != nil {
					t.Fatal(err)
				}
			}
			lifecycle, _ := s.lifecycleFile(*receipt.Binding)
			var state sessionLifecycle
			if err := readJSON(lifecycle, &state); err != nil {
				t.Fatal(err)
			}
			state.UnknownReason = "SESSION_START_UNTRACKED"
			state.CompletedKey = old.Key
			state.PromptHash = workspaceHash(sessionPrompt(oldDir, old))
			if invalid == "current prompt" {
				state.PromptHash = workspaceHash(sessionPrompt(dir, spec))
			}
			if err := writeJSON(lifecycle, state); err != nil {
				t.Fatal(err)
			}
			receipt.State = "submitting"
			if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
				t.Fatal(err)
			}
			user := func(text string) map[string]any {
				return map[string]any{"type": "user", "sessionId": receipt.Binding.ProviderID, "cwd": receipt.Binding.Directory, "promptId": "compact", "message": map[string]any{"content": text}}
			}
			summary := user("previous context")
			summary["isCompactSummary"] = true
			summary["isVisibleInTranscriptOnly"] = true
			records := []map[string]any{{"type": "system", "subtype": "compact_boundary", "sessionId": receipt.Binding.ProviderID, "cwd": receipt.Binding.Directory}, summary, user("<command-name>/compact</command-name>\n<command-message>compact</command-message>\n<command-args>retain context</command-args>"), user("<local-command-stdout>\x1b[2mCompacted (ctrl+o to see full summary)\x1b[22m</local-command-stdout>")}
			if invalid == "executed" {
				records = append(records, user(sessionPrompt(dir, spec)))
			}
			if invalid == "changed prefix" {
				prefix = append([]byte(" "), prefix...)
			}
			for _, record := range records {
				b, err := json.Marshal(record)
				if err != nil {
					t.Fatal(err)
				}
				prefix = append(prefix, b...)
				prefix = append(prefix, '\n')
			}
			if err := os.WriteFile(transcript, prefix, 0600); err != nil {
				t.Fatal(err)
			}
			result, err := s.ReconcileSession(context.Background(), spec.Key)
			if invalid != "" {
				if err == nil || result.Result != nil {
					t.Fatalf("accepted %s: %+v %v", invalid, result, err)
				}
				return
			}
			if err != nil || result.Result == nil || result.Result.ErrorCode != "SESSION_COMPACTION_INPUT_NOT_EXECUTED" || result.Result.InputStopped == nil || !*result.Result.InputStopped {
				t.Fatalf("not reconciled: %+v %v", result, err)
			}
			again, err := s.ReconcileSession(context.Background(), spec.Key)
			if err != nil || again.Result.StopEvidence != result.Result.StopEvidence {
				t.Fatal("repeat changed proof", err)
			}
		})
	}
}
