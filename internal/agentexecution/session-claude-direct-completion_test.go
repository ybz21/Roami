package agentexecution

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestPreparedClaudeReconcilesOnlyTheCompletedDirectInput(t *testing.T) {
	for _, mode := range []string{"automatic", "explicit", "pending tool", "wrong model", "wrong prompt", "blocked stop", "later input", "managed input", "foreign prepared provider"} {
		t.Run(mode, func(t *testing.T) {
			s, binding, _, transcript, _ := rejectedClaudeTask(t)
			const prepared = "original-prepared"
			const directPrompt = "Check the original work"
			initialDir, _ := s.directory(prepared)
			if err := os.MkdirAll(initialDir, 0700); err != nil {
				t.Fatal(err)
			}
			known := true
			origin := binding
			if mode == "foreign prepared provider" {
				origin.ProviderID = "other-provider"
			}
			for name, value := range map[string]any{
				"spec.json":    Spec{Key: prepared, Executor: "claude", Model: "free", Persistent: true},
				"receipt.json": Receipt{Session: binding.ID, Binding: &origin, Workspace: &Workspace{Directory: binding.Directory}},
				"result.json":  Result{State: "succeeded", InputStopped: &known, OutcomeKnown: &known},
			} {
				if err := writeJSON(filepath.Join(initialDir, name), value); err != nil {
					t.Fatal(err)
				}
			}
			path, _ := s.lifecycleFile(binding)
			state := sessionLifecycle{Executor: "claude", Binding: binding, Model: "free", State: "unknown",
				TurnID: "prompt", PromptHash: workspaceHash(directPrompt), Tools: map[string]bool{"denied-bash": true}}
			records := claudeDeniedCompletionTrace(binding, directPrompt, time.Now().Add(-time.Second).UnixMilli())
			for _, record := range records {
				if record["type"] == "assistant" {
					record["message"].(map[string]any)["model"] = "free"
				}
			}
			switch mode {
			case "pending tool":
				state.Tools["unmatched"] = true
			case "wrong model":
				records[3]["message"].(map[string]any)["model"] = "other-model"
			case "wrong prompt":
				state.PromptHash = workspaceHash("other input")
			case "blocked stop":
				records[4]["preventedContinuation"] = true
			case "later input":
				records = append(records, map[string]any{"type": "user", "promptId": "later", "message": map[string]any{"content": "later"}})
			case "managed input":
				state.LaunchKey = "other-managed-execution"
			}
			writeReportRecords(t, transcript, records)
			if err := writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			next := Spec{Key: "next", Executor: "claude", SessionID: binding.ID, PreparedFrom: prepared, Prompt: "Read the next result"}
			if mode == "explicit" {
				prior, err := s.Status(prepared)
				if err != nil || prior.Result == nil {
					t.Fatalf("original result missing: %+v %v", prior, err)
				}
				for i := 0; i < 2; i++ {
					status, err := s.ReconcileSession(context.Background(), prepared)
					if err != nil || status.Result == nil || status.Result.Summary != prior.Result.Summary || status.Result.FinishedMS != prior.Result.FinishedMS {
						t.Fatalf("direct reconciliation changed the original result: %+v %v", status, err)
					}
				}
				if ready, err := s.PreparedSession(prepared); err != nil || !ready.Ready || ready.SessionID != binding.ID {
					t.Fatalf("original session not ready: %+v %v", ready, err)
				}
			}
			if mode != "explicit" && mode != "automatic" {
				if _, err := s.ReconcileSession(context.Background(), prepared); err == nil {
					t.Fatal("unconfirmed input explicitly reconciled")
				}
				if _, err := s.Launch(context.Background(), next); err == nil {
					t.Fatal("unconfirmed input allowed new execution")
				}
				if _, err := os.Stat(directClaudeCompletionPath(path, state.TurnID)); !os.IsNotExist(err) {
					t.Fatal("unconfirmed input wrote completion proof")
				}
				return
			}
			// The helper fixture left a previous writer. Mark that unrelated fixture run settled.
			old, _ := s.directory("claude-rejected")
			if err := writeJSON(filepath.Join(old, "result.json"), Result{State: "failed", InputStopped: &known, OutcomeKnown: &known}); err != nil {
				t.Fatal(err)
			}
			launched, err := s.Launch(context.Background(), next)
			if err != nil || launched.Session != binding.ID || launched.Binding == nil || launched.Binding.ProviderID != binding.ProviderID || launched.Result != nil {
				t.Fatalf("original session did not keep its identity: %+v %v", launched, err)
			}
			var proof completionSource
			if err := readJSON(directClaudeCompletionPath(path, state.TurnID), &proof); err != nil || proof.ProviderID != binding.ProviderID || len(proof.TranscriptSHA256) != 64 {
				t.Fatalf("missing direct completion proof: %+v %v", proof, err)
			}
		})
	}
}
