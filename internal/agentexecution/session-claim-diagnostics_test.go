package agentexecution

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestOriginalSessionClaimRetainsPreStartDiagnostics(t *testing.T) {
	for _, busy := range []bool{true, false} {
		name := "prior-unknown"
		if busy {
			name = "active-writer"
		}
		t.Run(name, func(t *testing.T) {
			s, binding := sessionFixture(t)
			seedSession(t, s, binding)
			lease, err := s.claimWorkspace(context.Background(), binding.Directory, "prior-writer")
			if err != nil {
				t.Fatal(err)
			}
			defer lease()
			prior, _ := s.directory("prior-writer")
			if err := os.MkdirAll(prior, 0700); err != nil {
				t.Fatal(err)
			}
			if err := writeJSON(filepath.Join(prior, "receipt.json"), Receipt{Session: "prior-session", State: "running"}); err != nil {
				t.Fatal(err)
			}
			if !busy {
				lease()
			}
			fence := filepath.Join(s.Runtime.DataDir, "agents", "workspace-leases", workspaceHash(binding.Directory), "writer.json")
			before, err := os.ReadFile(fence)
			if err != nil {
				t.Fatal(err)
			}
			path, err := s.lifecycleFile(binding)
			if err != nil {
				t.Fatal(err)
			}
			lifecycle, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			spec := Spec{Key: "blocked-original", Executor: "codex", SessionID: binding.ID, Prompt: "Never submitted", TimeoutSeconds: 30}
			status, err := s.Launch(context.Background(), spec)
			if err != nil || status.Result == nil {
				t.Fatalf("missing refusal: %+v %v", status, err)
			}
			result := status.Result
			code, reason := "WORKSPACE_OUTCOME_UNKNOWN", "WORKSPACE_PRIOR_RESULT_MISSING"
			if busy {
				code, reason = "WORKSPACE_BUSY", "WORKSPACE_BUSY"
			}
			if result.ExecutionStarted == nil || *result.ExecutionStarted || result.ExitCodeSource != "not_started" || result.ErrorCode != code || result.Failure == nil || result.Failure.Phase != "workspace_claim" || result.Failure.ReasonCode != reason {
				t.Fatalf("missing diagnostics: %+v", result)
			}
			if !busy && (result.Failure.BlockingSessionID != "prior-session" || result.Failure.BlockingExecutionID != filepath.Base(prior)) {
				t.Fatalf("missing blocker: %+v", result.Failure)
			}
			if result.OutcomeKnown != nil || result.InputStopped != nil {
				t.Fatal("invented prior stop/effects")
			}
			after, _ := os.ReadFile(fence)
			current, _ := os.ReadFile(path)
			if !bytes.Equal(before, after) || !bytes.Equal(lifecycle, current) {
				t.Fatal("prior writer/session changed")
			}
			if _, err := os.Stat(filepath.Join(s.Runtime.DataDir, "submits")); !os.IsNotExist(err) {
				t.Fatal("new prompt submitted")
			}
			again, err := s.Launch(context.Background(), spec)
			if err != nil || again.Result == nil || again.Result.ErrorCode != code {
				t.Fatalf("lost replay receipt: %+v %v", again, err)
			}
		})
	}
}
