package agentexecution

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestNativeHoldPersistsPreStartWorkspaceClaimFailure(t *testing.T) {
	for _, tc := range []struct{ name, result, reason string }{
		{"missing", "", "WORKSPACE_PRIOR_RESULT_MISSING"},
		{"unreadable", "private invalid result", "WORKSPACE_PRIOR_RESULT_UNREADABLE"},
		{"active", `{"state":"running"}`, "WORKSPACE_PRIOR_RESULT_NOT_TERMINAL"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s := testService(t)
			directory := t.TempDir()
			prior := seedBlockedWriter(t, s, directory)
			if tc.result != "" {
				if err := os.WriteFile(filepath.Join(prior, "result.json"), []byte(tc.result), 0600); err != nil {
					t.Fatal(err)
				}
			}
			var output bytes.Buffer
			spec := Spec{Key: "blocked-native", Executor: "native", Directory: directory}
			err := s.HoldNative(context.Background(), spec, json.NewDecoder(strings.NewReader("")), &output)
			if err == nil || err.Error() != "WORKSPACE_OUTCOME_UNKNOWN" {
				t.Fatalf("missing refusal: %v", err)
			}
			var frame Result
			if err := json.Unmarshal(output.Bytes(), &frame); err != nil {
				t.Fatal(err)
			}
			status, err := s.Status(spec.Key)
			if err != nil || status.State != "failed" || status.Result == nil {
				t.Fatalf("lost durable rejection: %+v %v", status, err)
			}
			stored, _ := json.Marshal(status.Result)
			wire, _ := json.Marshal(frame)
			if !bytes.Equal(stored, wire) || frame.ExecutionStarted == nil || *frame.ExecutionStarted || frame.ExitCodeSource != "not_started" || frame.Failure == nil || frame.Failure.ReasonCode != tc.reason || frame.Failure.BlockingExecutionID != filepath.Base(prior) || frame.Failure.BlockingSessionID != "prior-session" {
				t.Fatalf("lost safe pre-start facts: %s", wire)
			}
			launch, _ := s.directory(spec.Key)
			if _, err := os.Stat(filepath.Join(launch, "started")); !os.IsNotExist(err) {
				t.Fatal("blocked native execution started")
			}
			lease := filepath.Join(s.Runtime.DataDir, "agents", "workspace-leases", workspaceHash(directory), "writer.json")
			var writer struct {
				Key string `json:"key"`
			}
			if readJSON(lease, &writer) != nil || writer.Key != "prior-writer" || strings.Contains(output.String(), "private") {
				t.Fatal("prior fence changed or raw diagnostics escaped")
			}
		})
	}
}

func seedBlockedWriter(t *testing.T, s Service, directory string) string {
	t.Helper()
	release, err := s.claimWorkspace(context.Background(), directory, "prior-writer")
	if err != nil {
		t.Fatal(err)
	}
	release()
	prior, _ := s.directory("prior-writer")
	if err = os.MkdirAll(prior, 0700); err != nil {
		t.Fatal(err)
	}
	if err = writeJSON(filepath.Join(prior, "receipt.json"), Receipt{Session: "prior-session", State: "running"}); err != nil {
		t.Fatal(err)
	}
	return prior
}

func TestWorkspaceClaimFailureDistinguishesPriorEvidence(t *testing.T) {
	for _, tc := range []struct{ name, result, reason string }{
		{"missing", "", "WORKSPACE_PRIOR_RESULT_MISSING"},
		{"malformed", "private content: not JSON", "WORKSPACE_PRIOR_RESULT_UNREADABLE"},
		{"nonterminal", `{"state":"running"}`, "WORKSPACE_PRIOR_RESULT_NOT_TERMINAL"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s := testService(t)
			directory := t.TempDir()
			prior := seedBlockedWriter(t, s, directory)
			if tc.result != "" {
				if err := os.WriteFile(filepath.Join(prior, "result.json"), []byte(tc.result), 0600); err != nil {
					t.Fatal(err)
				}
			}
			release, err := s.claimWorkspace(context.Background(), directory, "new-writer")
			if err == nil {
				release()
				t.Fatal("unknown writer was admitted")
			}
			result := workspaceClaimResult(err)
			if result.Summary != tc.reason || result.ErrorCode != "WORKSPACE_OUTCOME_UNKNOWN" || result.ExecutionStarted == nil || *result.ExecutionStarted || result.ExitCode != -1 || result.ExitCodeSource != "not_started" || result.Failure == nil || result.Failure.Phase != "workspace_claim" || result.Failure.ReasonCode != tc.reason || result.Failure.BlockingExecutionID != filepath.Base(prior) || result.Failure.BlockingSessionID != "prior-session" {
				t.Fatalf("lost pre-start evidence: %+v failure=%+v", result, result.Failure)
			}
			raw, _ := json.Marshal(result)
			if strings.Contains(string(raw), "private") || strings.Contains(string(raw), "prior-writer") {
				t.Fatalf("raw diagnostics escaped: %s", raw)
			}
			root, unlock, err := s.lockWorkspaceWriter(context.Background(), directory)
			if err != nil {
				t.Fatal(err)
			}
			defer unlock()
			var writer struct {
				Key string `json:"key"`
			}
			if readJSON(filepath.Join(root, "writer.json"), &writer) != nil || writer.Key != "prior-writer" {
				t.Fatal("rejection changed prior fence")
			}
		})
	}
}

func TestWorkspaceClaimFailurePersistsBeforeExecutorInvocation(t *testing.T) {
	for _, kind := range []string{"claude", "codex", "pi"} {
		t.Run(kind, func(t *testing.T) {
			s := testService(t)
			directory := t.TempDir()
			prior := seedBlockedWriter(t, s, directory)
			dir, _ := s.directory("blocked-launch")
			if err := os.MkdirAll(dir, 0700); err != nil {
				t.Fatal(err)
			}
			// The fake CLI permits capability probing but records any actual executor invocation.
			binary := filepath.Join(dir, kind)
			marker := filepath.Join(dir, "executor-invoked")
			script := "#!/bin/sh\nif [ \"$1\" = --help ]; then printf '%s' --settings; exit 0; fi\ntouch " + quote(marker) + "\nexit 99\n"
			if err := os.WriteFile(binary, []byte(script), 0700); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
			spec := Spec{Key: "blocked-launch", Executor: kind, Directory: directory, Prompt: "write deliverable", Persistent: kind == "claude"}
			receipt := Receipt{State: "launched", Workspace: &Workspace{Directory: directory}}
			if kind == "claude" {
				// Use a fake identity transport, never the user's tmux server.
				receipt.Session = "2026-1017-0900-0001"
				tmux := filepath.Join(dir, "tmux")
				identity := "2026-1017-0900-0001\t$1\t1792200000\tfixture\t%3\t1\t" + directory + "\n"
				script := "#!/bin/sh\ncase \"$1\" in\nlist-sessions) printf '" + receipt.Session + "\\t1792200000\\t" + receipt.Session + "\\tlabel\\n';;\nlist-panes) printf '%s' " + quote(identity) + ";;\n*) exit 1;;\nesac\n"
				if err := os.WriteFile(tmux, []byte(script), 0700); err != nil {
					t.Fatal(err)
				}
				s.Runtime.TmuxBin = tmux
			}
			if err := writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
				t.Fatal(err)
			}
			if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
				t.Fatal(err)
			}
			err := s.Run(context.Background(), spec.Key, io.Discard, io.Discard)
			if kind != "codex" && (err == nil || err.Error() != "WORKSPACE_OUTCOME_UNKNOWN") {
				t.Fatalf("runner failure: %v", err)
			}
			if kind == "codex" && err != nil {
				t.Fatal(err)
			}
			status, err := s.Status(spec.Key)
			if err != nil || status.Result == nil {
				t.Fatalf("durable status: %+v %v", status, err)
			}
			result := status.Result
			if result.State != "failed" || result.ExecutionStarted == nil || *result.ExecutionStarted || result.Failure == nil || result.Failure.ReasonCode != "WORKSPACE_PRIOR_RESULT_MISSING" || result.Failure.BlockingExecutionID != filepath.Base(prior) {
				t.Fatalf("lost diagnostics: %+v", result)
			}
			if _, err = os.Stat(marker); !os.IsNotExist(err) {
				t.Fatal("executor was invoked before workspace admission")
			}
			if _, err = os.Stat(filepath.Join(dir, "prompt.txt")); !os.IsNotExist(err) {
				t.Fatal("task prompt was handed off before workspace admission")
			}
			t.Logf("%s: phase=%s executionStarted=%t exitCodeSource=%s reason=%s", kind, result.Failure.Phase, *result.ExecutionStarted, result.ExitCodeSource, result.Failure.ReasonCode)
		})
	}
}
