package agentexecution

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func missingClaudeRejection(t *testing.T) (Service, Spec, Receipt, string) {
	t.Helper()
	s, key, receipt := missingExecutionFixture(t)
	binding := receipt.Binding
	binding.ProviderID = reportProviderID
	binding.HostProof = sessionHostProof()
	binding.DirectoryProof = sessionDirectoryProof(binding.Directory)
	home := t.TempDir()
	project := filepath.Join(home, "projects", "workspace")
	if err := os.MkdirAll(project, 0700); err != nil {
		t.Fatal(err)
	}
	binding.ProviderHome = home
	binding.ProviderHomeProof = sessionDirectoryProof(home)
	workspace, err := s.rememberWorkspace(Workspace{Directory: binding.Directory})
	if err != nil {
		t.Fatal(err)
	}
	receipt.Workspace = &workspace
	spec := Spec{Key: key, Executor: "claude", SessionID: receipt.Session, Prompt: "Collect evidence", Persistent: true, TimeoutSeconds: 120}
	dir, _ := s.directory(key)
	if err := writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		t.Fatal(err)
	}
	state := sessionLifecycle{Binding: *binding, Workspace: &workspace, Executor: "claude", State: "unknown", UnknownReason: "SESSION_PROMPT_MISMATCH", TurnID: "prompt", PromptHash: workspaceHash(sessionPrompt(dir, spec)), LaunchKey: key, Tools: map[string]bool{}}
	path, _ := s.lifecycleFile(*binding)
	if err := writeJSON(path, state); err != nil {
		t.Fatal(err)
	}
	transcript := filepath.Join(project, reportProviderID+".jsonl")
	records := claudeChangedFailureRecords(*binding, sessionPrompt(dir, spec), "prompt", true)
	records = append(records, map[string]any{"type": "cost-state"})
	writeReportRecords(t, transcript, records)
	release, err := s.claimWorkspace(context.Background(), binding.Directory, key)
	if err != nil {
		t.Fatal(err)
	}
	release()
	return s, spec, receipt, transcript
}

func TestMissingClaudeRequiresRejectedWindowAndPreservesProviderRecovery(t *testing.T) {
	s, spec, receipt, _ := missingClaudeRejection(t)
	before, err := s.Status(spec.Key)
	if err != nil || before.State != "unknown" || before.Result == nil || before.Result.InputStopped == nil || *before.Result.InputStopped {
		t.Fatalf("absence became proof: %+v %v", before, err)
	}
	result, err := s.ReconcileSession(context.Background(), spec.Key)
	if err != nil || result.State != "failed" || result.Result == nil || result.Result.Summary != "SESSION_SCOPE_CHANGED_STOPPED" || result.Result.InputStopped == nil || !*result.Result.InputStopped || result.Result.OutcomeKnown == nil || !*result.Result.OutcomeKnown || len(result.Result.StopEvidence) != 64 {
		t.Fatalf("missing rejection not proved: %+v %v", result, err)
	}
	again, err := s.ReconcileSession(context.Background(), spec.Key)
	if err != nil || again.Result.FinishedMS != result.Result.FinishedMS {
		t.Fatal("repeat changed proof")
	}
	path, _ := s.lifecycleFile(*receipt.Binding)
	var state sessionLifecycle
	if err := readJSON(path, &state); err != nil {
		t.Fatal(err)
	}
	if !state.EndedIdle || state.CompletedKey != spec.Key || state.Binding.ProviderID != reportProviderID {
		t.Fatal("original provider binding lost")
	}
	next := spec
	next.Key = "recover-rejected-provider"
	next.ResumeFrom = spec.Key
	next.ResumeProvider = reportProviderID
	source := providerRecoverySource{Spec: spec, Receipt: receipt, Lifecycle: state}
	workspace, err := s.providerRecovery(context.Background(), next, source)
	if err != nil || workspace.Directory != receipt.Workspace.Directory {
		t.Fatalf("rejected provider cannot recover: %+v %v", workspace, err)
	}
	dir, _ := s.directory(spec.Key)
	if err := writeJSON(filepath.Join(dir, "closed.json"), map[string]bool{"closed": true}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.providerRecovery(context.Background(), next, source); err == nil {
		t.Fatal("explicit close bypassed")
	}
}

func TestMissingClaudeRejectionRejectsIncompleteOrForeignEvidence(t *testing.T) {
	for _, mode := range []string{"live session", "transport error", "live process", "foreign host", "pending tool", "binding changed", "directory changed", "normal reply", "pending input"} {
		t.Run(mode, func(t *testing.T) {
			s, spec, receipt, transcript := missingClaudeRejection(t)
			statePath, _ := s.lifecycleFile(*receipt.Binding)
			var state sessionLifecycle
			if err := readJSON(statePath, &state); err != nil {
				t.Fatal(err)
			}
			switch mode {
			case "live session":
				script := "#!/bin/sh\n[ \"$1\" = list-sessions ] && printf '$1\\t1792200000\\t" + receipt.Binding.Name + "\\tlabel\\n'\n"
				if err := os.WriteFile(s.Runtime.TmuxBin, []byte(script), 0700); err != nil {
					t.Fatal(err)
				}
			case "transport error":
				if err := os.WriteFile(s.Runtime.TmuxBin, []byte("#!/bin/sh\necho permission denied >&2\nexit 1\n"), 0700); err != nil {
					t.Fatal(err)
				}
			case "live process":
				receipt.Binding.Processes[os.Getpid()] = observedProcessToken(os.Getpid())
				state.Binding = *receipt.Binding
			case "foreign host":
				receipt.Binding.HostProof = "foreign"
				state.Binding = *receipt.Binding
			case "pending tool":
				state.Tools["pending"] = true
			case "binding changed":
				state.Binding.ProviderID = "foreign"
			case "directory changed":
				receipt.Binding.DirectoryProof = "changed"
				state.Binding = *receipt.Binding
			case "normal reply", "pending input":
				dir, _ := s.directory(spec.Key)
				records := claudeChangedFailureRecords(*receipt.Binding, sessionPrompt(dir, spec), "prompt", true)
				if mode == "normal reply" {
					records[len(records)-2]["message"].(map[string]any)["model"] = "real-model"
				} else {
					records = records[:len(records)-1]
				}
				writeReportRecords(t, transcript, records)
			}
			dir, _ := s.directory(spec.Key)
			if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
				t.Fatal(err)
			}
			if err := writeJSON(statePath, state); err != nil {
				t.Fatal(err)
			}
			if status, err := s.ReconcileSession(context.Background(), spec.Key); err == nil || status.Result != nil {
				t.Fatalf("%s accepted: %+v %v", mode, status, err)
			}
			if _, err := os.Stat(filepath.Join(dir, "result.json")); !os.IsNotExist(err) {
				t.Fatal("rejection wrote a result")
			}
		})
	}
}
