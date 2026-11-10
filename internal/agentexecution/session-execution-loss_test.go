package agentexecution

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/ybz21/Roami/internal/memguard"
)

func missingExecutionFixture(t *testing.T) (Service, string, Receipt) {
	t.Helper()
	s := testService(t)
	key := "missing-session"
	dir, _ := s.directory(key)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(s.Runtime.DataDir, "tmux")
	if err := os.WriteFile(bin, []byte("#!/bin/sh\n[ \"$1\" = list-sessions ] && exit 0\nexit 1\n"), 0700); err != nil {
		t.Fatal(err)
	}
	s.Runtime.TmuxBin = bin
	scope := "/sys/fs/cgroup/" + filepath.Base(t.TempDir()) + "/tmux-spawn-missing.scope"
	if pids, err := memguard.RecordedScopeProcesses(scope); err != nil || len(pids) != 0 {
		t.Skip("requires readable cgroup v2 observation")
	}
	binding := &SessionBinding{Name: "2026-1017-0900-0001", ID: "2026-1017-0900-0001", TmuxID: "$1", Created: "1792200000", Server: "old-server", Pane: "%3", PID: 1 << 30, Processes: map[int]string{1 << 30: "old-start-token"}, Scope: scope, Directory: t.TempDir(), ProviderID: "old-provider"}
	receipt := Receipt{Session: binding.ID, State: "running", Binding: binding}
	if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		t.Fatal(err)
	}
	return s, key, receipt
}

func TestMissingSessionLeavesUnknownEffectsAndWorkspaceFence(t *testing.T) {
	s, key, receipt := missingExecutionFixture(t)
	release, err := s.claimWorkspace(context.Background(), receipt.Binding.Directory, key)
	if err != nil {
		t.Fatal(err)
	}
	release()
	dir, _ := s.directory(key)
	before, _ := os.ReadFile(filepath.Join(dir, "receipt.json"))
	for range 2 {
		status, err := s.Status(key)
		if err != nil || status.State != "unknown" || status.ObservationErrorCode != "SESSION_EXECUTION_MISSING" || status.Result == nil {
			t.Fatalf("missing execution: %+v %v", status, err)
		}
		if status.Result.InputStopped == nil || *status.Result.InputStopped || status.Result.OutcomeKnown == nil || *status.Result.OutcomeKnown || status.Result.FinishedMS != 0 {
			t.Fatalf("absence became completion evidence: %+v", status.Result)
		}
	}
	if _, err := os.Stat(filepath.Join(dir, "result.json")); !os.IsNotExist(err) {
		t.Fatal("status wrote a terminal execution journal")
	}
	after, _ := os.ReadFile(filepath.Join(dir, "receipt.json"))
	if string(before) != string(after) {
		t.Fatal("status changed the original binding")
	}
	if _, err := s.claimWorkspace(context.Background(), receipt.Binding.Directory, "another-task"); err == nil || err.Error() != "WORKSPACE_OUTCOME_UNKNOWN" {
		t.Fatalf("unconfirmed writer was released: %v", err)
	}
}

func TestMissingExecutionRequiresBothSessionAndProcessAbsence(t *testing.T) {
	for _, mode := range []string{"live-session", "transport-error", "captured-process-alive", "untracked-process", "invalid-scope", "foreign-host", "known-result"} {
		t.Run(mode, func(t *testing.T) {
			s, key, receipt := missingExecutionFixture(t)
			dir, _ := s.directory(key)
			switch mode {
			case "live-session":
				line := fmt.Sprintf("#!/bin/sh\n[ \"$1\" = list-sessions ] && printf '$1\\t1792200000\\t%s\\tlabel\\n'\n", receipt.Binding.Name)
				if err := os.WriteFile(s.Runtime.TmuxBin, []byte(line), 0700); err != nil {
					t.Fatal(err)
				}
			case "transport-error":
				if err := os.WriteFile(s.Runtime.TmuxBin, []byte("#!/bin/sh\necho 'permission denied' >&2\nexit 1\n"), 0700); err != nil {
					t.Fatal(err)
				}
			case "captured-process-alive":
				receipt.Binding.Processes[os.Getpid()] = observedProcessToken(os.Getpid())
			case "untracked-process":
				receipt.Binding.Processes = nil
			case "invalid-scope":
				receipt.Binding.Scope = "/tmp/tmux-spawn-not-a-cgroup.scope"
			case "foreign-host":
				receipt.Binding.HostProof = "another-host"
			case "known-result":
				known := true
				if err := writeJSON(filepath.Join(dir, "result.json"), Result{State: "succeeded", Summary: "Verified result", InputStopped: &known, OutcomeKnown: &known}); err != nil {
					t.Fatal(err)
				}
			}
			if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
				t.Fatal(err)
			}
			status, err := s.Status(key)
			if err != nil {
				t.Fatal(err)
			}
			if mode == "known-result" {
				if status.Result == nil || status.Result.State != "succeeded" {
					t.Fatal("known result was replaced")
				}
			} else if status.Result != nil || status.ObservationErrorCode == "SESSION_EXECUTION_MISSING" {
				t.Fatalf("%s incorrectly released admission: %+v", mode, status)
			}
		})
	}
}
