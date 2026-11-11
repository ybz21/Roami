package agentexecution

import (
	"context"
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func interruptedClaudeRecords(binding SessionBinding, prompt, turn string, since int64, compact bool) []map[string]any {
	record := func(kind, id, parent string, offset int64, content any) map[string]any {
		return map[string]any{"type": kind, "uuid": id, "parentUuid": parent, "sessionId": binding.ProviderID, "promptId": turn, "cwd": binding.Directory, "timestamp": time.UnixMilli(since + offset).UTC().Format(time.RFC3339Nano), "message": map[string]any{"content": content}}
	}
	records := []map[string]any{
		record("user", "root", "", -100, prompt),
		record("assistant", "calls", "root", -80, []any{map[string]any{"type": "tool_use", "id": "read", "name": "Read", "input": map[string]any{"file_path": "report.md"}}, map[string]any{"type": "tool_use", "id": "blocked", "name": "Bash", "input": map[string]any{"command": "true"}}}),
		record("user", "read-result", "calls", -60, []any{map[string]any{"type": "tool_result", "tool_use_id": "read", "content": "retained evidence"}}),
		record("user", "blocked-result", "read-result", -40, []any{map[string]any{"type": "tool_result", "tool_use_id": "blocked", "is_error": true, "content": "permission check unavailable"}}),
	}
	parent := "blocked-result"
	if compact {
		boundary := record("system", "compact", "", -30, nil)
		boundary["subtype"], boundary["logicalParentUuid"] = "compact_boundary", parent
		summary := record("user", "summary", "compact", -20, "provider compaction summary")
		summary["isCompactSummary"], summary["isVisibleInTranscriptOnly"] = true, true
		records = append(records, boundary, summary)
		parent = "summary"
	}
	records = append(records, record("user", "interrupted", parent, 1, "[Request interrupted by user]"), map[string]any{"type": "cost-state"})
	return records
}

func TestClaudeInterruptedEvidenceRequiresCompleteScopedTerminalWindow(t *testing.T) {
	for _, mode := range []string{"normal", "compact", "tool search", "file history delta", "late file history delta", "wrong hash", "wrong prompt", "wrong provider", "wrong cwd", "sidechain", "wrong parent", "duplicate uuid", "missing result", "duplicate call", "missing marker", "marker in output", "old marker", "future marker", "wrong marker turn", "later user", "later assistant", "later request", "unknown metadata", "background", "untyped background", "agent", "historical agent", "compact gap", "hidden summary", "untracked summary", "malformed", "writable", "symlink", "oversize"} {
		t.Run(mode, func(t *testing.T) {
			binding, path, _, prompt := reportFixture(t)
			since := time.Now().UnixMilli()
			records := interruptedClaudeRecords(binding, prompt, "turn", since, mode == "compact" || mode == "compact gap" || mode == "hidden summary" || mode == "untracked summary")
			hash := workspaceHash(prompt)
			marker := len(records) - 2
			switch mode {
			case "file history delta":
				records = append(records[:marker], append([]map[string]any{{"type": "file-history-delta", "messageId": "calls", "trackingPath": "report.md"}}, records[marker:]...)...)
			case "late file history delta":
				records = append(records, map[string]any{"type": "file-history-delta", "messageId": "calls", "trackingPath": "report.md"})
			case "wrong hash":
				hash = workspaceHash("other")
			case "wrong prompt":
				records[0]["promptId"] = "other"
			case "wrong provider":
				records[1]["sessionId"] = "other"
			case "wrong cwd":
				records[1]["cwd"] = t.TempDir()
			case "sidechain":
				records[2]["isSidechain"] = true
			case "wrong parent":
				records[2]["parentUuid"] = "foreign"
			case "duplicate uuid":
				records[2]["uuid"] = "calls"
			case "missing result":
				records = append(records[:2], records[3:]...)
			case "duplicate call":
				records[1]["message"].(map[string]any)["content"].([]any)[1].(map[string]any)["id"] = "read"
			case "missing marker":
				records = records[:marker]
			case "marker in output":
				records[2]["message"].(map[string]any)["content"].([]any)[0].(map[string]any)["content"] = "[Request interrupted by user]"
				records = records[:marker]
			case "old marker":
				records[marker]["timestamp"] = time.UnixMilli(since - 1).UTC().Format(time.RFC3339Nano)
			case "future marker":
				records[marker]["timestamp"] = time.Now().Add(time.Hour).UTC().Format(time.RFC3339Nano)
			case "wrong marker turn":
				records[marker]["promptId"] = "other"
			case "later user", "later assistant", "later request":
				kind := map[string]string{"later user": "user", "later assistant": "assistant", "later request": "api-request"}[mode]
				records = append(records, map[string]any{"type": kind, "message": map[string]any{"content": "later"}})
			case "unknown metadata":
				records = append(records[:2], append([]map[string]any{{"type": "new-unproved-action"}}, records[2:]...)...)
			case "background":
				records[1]["message"].(map[string]any)["content"].([]any)[1].(map[string]any)["input"].(map[string]any)["run_in_background"] = true
			case "untyped background":
				records[1]["message"].(map[string]any)["content"].([]any)[1].(map[string]any)["input"].(map[string]any)["run_in_background"] = "true"
			case "agent":
				records[1]["message"].(map[string]any)["content"].([]any)[1].(map[string]any)["name"] = "Agent"
			case "historical agent":
				records = append([]map[string]any{{"type": "assistant", "message": map[string]any{"content": []any{map[string]any{"type": "tool_use", "name": "Agent"}}}}}, records...)
			case "tool search":
				records[1]["message"].(map[string]any)["content"].([]any)[0].(map[string]any)["name"] = "ToolSearch"
			case "compact gap":
				records[4]["logicalParentUuid"] = "foreign"
			case "hidden summary":
				records[5]["isVisibleInTranscriptOnly"] = false
			case "untracked summary":
				records = append(records[:4], records[5:]...)
			}
			writeReportRecords(t, path, records)
			switch mode {
			case "malformed":
				if err := os.WriteFile(path, []byte("broken"), 0600); err != nil {
					t.Fatal(err)
				}
			case "writable":
				if err := os.Chmod(path, 0666); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				original := path + ".original"
				if err := os.Rename(path, original); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(original, path); err != nil {
					t.Fatal(err)
				}
			case "oversize":
				if err := os.Truncate(path, (64<<20)+1); err != nil {
					t.Fatal(err)
				}
			}
			result, digest, completed := claudeInterruptedEvidence(binding, "turn", hash, since)
			want := mode == "normal" || mode == "compact" || mode == "tool search" || mode == "file history delta" || mode == "late file history delta"
			if !want {
				if result != nil {
					t.Fatalf("unproved %s accepted", mode)
				}
				return
			}
			if result == nil || result.State != "failed" || result.ErrorCode != "CLAUDE_SESSION_INTERRUPTED" || len(digest) != 64 || len(completed) != 2 {
				t.Fatalf("missing interruption proof: %+v %q %+v", result, digest, completed)
			}
		})
	}
}

func interruptedClaudeTask(t *testing.T) (Service, SessionBinding, Spec, string, []map[string]any) {
	t.Helper()
	s, binding := sessionFixture(t)
	home := t.TempDir()
	t.Setenv("CLAUDE_CONFIG_DIR", home)
	binding.HostProof, binding.DirectoryProof = sessionHostProof(), sessionDirectoryProof(binding.Directory)
	binding.ProviderHome, binding.ProviderHomeProof = home, sessionDirectoryProof(home)
	for _, event := range []SessionEvent{claudeEvent("UserPromptSubmit", "seed"), claudeEvent("Stop", "seed"), claudeEvent("Notification", "seed")} {
		event.ProviderID = reportProviderID
		event.Prompt = "manual seed"
		event.NotificationType = "idle_prompt"
		if err := s.applySessionEvent("claude", binding, event); err != nil {
			t.Fatal(err)
		}
	}
	spec := Spec{Key: "claude-interrupted", Executor: "claude", SessionID: binding.ID, Prompt: "Read existing evidence", Persistent: true}
	status, err := s.Launch(context.Background(), spec)
	if err != nil {
		t.Fatal(err)
	}
	binding = *status.Binding
	dir, _ := s.directory(spec.Key)
	prompt := sessionPrompt(dir, spec)
	start := claudeEvent("UserPromptSubmit", "turn")
	start.ProviderID = reportProviderID
	start.Prompt = prompt
	if err := s.applySessionEvent("claude", binding, start); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"read", "blocked"} {
		tool := claudeEvent("PreToolUse", "turn")
		tool.ProviderID = reportProviderID
		tool.ToolID = id
		if err := s.applySessionEvent("claude", binding, tool); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := s.Cancel(spec.Key); err != nil {
		t.Fatal(err)
	}
	var intent sessionInterrupt
	if err := readJSON(filepath.Join(dir, "interrupt-request.json"), &intent); err != nil {
		t.Fatal(err)
	}
	folder := filepath.Join(home, "projects", "fixture")
	if err := os.MkdirAll(folder, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(folder, reportProviderID+".jsonl")
	records := interruptedClaudeRecords(binding, prompt, "turn", intent.CreatedMS, true)
	writeReportRecords(t, path, records)
	return s, binding, spec, path, records
}

func TestClaudeInterruptedReconciliationPreservesFailureAndOriginalProvider(t *testing.T) {
	s, binding, spec, _, _ := interruptedClaudeTask(t)
	before, err := s.Status(spec.Key)
	if err != nil || before.Result != nil || before.State != "cancelling" {
		t.Fatalf("ordinary status weakened: %+v %v", before, err)
	}
	result, err := s.ReconcileSession(t.Context(), spec.Key)
	if err != nil || result.Result == nil || result.State != "failed" || result.Result.ErrorCode != "CLAUDE_SESSION_INTERRUPTED" || result.Result.InputStopped == nil || !*result.Result.InputStopped || result.Result.OutcomeKnown == nil || !*result.Result.OutcomeKnown || result.Binding.ProviderID != binding.ProviderID {
		t.Fatalf("formal proof: %+v %v", result, err)
	}
	dir, _ := s.directory(spec.Key)
	var audit struct {
		Completed map[string]int64 `json:"completedTools"`
	}
	if err := readJSON(filepath.Join(dir, "claude-interruption-reconciliation.json"), &audit); err != nil || len(audit.Completed) != 2 {
		t.Fatalf("audit missing: %+v %v", audit, err)
	}
	again, err := s.ReconcileSession(t.Context(), spec.Key)
	if err != nil || again.Result.StopEvidence != result.Result.StopEvidence {
		t.Fatalf("replay changed proof: %+v %v", again, err)
	}
	spec.Key = "same-role-next-turn"
	spec.Prompt = "Continue with retained evidence"
	next, err := s.Launch(t.Context(), spec)
	if err != nil || next.Session != binding.ID || next.Binding.ProviderID != binding.ProviderID {
		t.Fatalf("provider replaced: %+v %v", next, err)
	}
}

func TestClaudeInterruptedReconciliationRejectsMissingCustodyAndActiveWriters(t *testing.T) {
	for _, mode := range []string{"missing cancel", "missing intent", "undelivered", "wrong turn", "unrecorded hook", "subagent hook", "live writer", "other workspace", "foreign provider", "changed input"} {
		t.Run(mode, func(t *testing.T) {
			s, binding, spec, path, records := interruptedClaudeTask(t)
			dir, _ := s.directory(spec.Key)
			life, _ := s.lifecycleFile(binding)
			var state sessionLifecycle
			if err := readJSON(life, &state); err != nil {
				t.Fatal(err)
			}
			switch mode {
			case "missing cancel":
				if err := os.Remove(filepath.Join(dir, "cancel.json")); err != nil {
					t.Fatal(err)
				}
			case "missing intent":
				if err := os.Remove(filepath.Join(dir, "interrupt-request.json")); err != nil {
					t.Fatal(err)
				}
			case "undelivered", "wrong turn":
				var intent sessionInterrupt
				if err := readJSON(filepath.Join(dir, "interrupt-request.json"), &intent); err != nil {
					t.Fatal(err)
				}
				if mode == "undelivered" {
					intent.Delivered = false
				} else {
					intent.TurnID = "other"
				}
				if err := writeJSON(filepath.Join(dir, "interrupt-request.json"), intent); err != nil {
					t.Fatal(err)
				}
			case "unrecorded hook":
				state.Tools["unproved"] = true
			case "subagent hook":
				state.Tools["subagent:unproved"] = true
			case "foreign provider":
				state.ProviderConflict = &sessionProviderConflict{ProviderID: "foreign"}
			case "live writer":
				worker, _ := claudeCancellationWorker(t)
				if worker.Process.Signal(syscall.Signal(0)) != nil {
					t.Fatal("fixture writer absent")
				}
			case "other workspace":
				root, release, err := s.lockWorkspaceWriter(t.Context(), binding.Directory)
				if err != nil {
					t.Fatal(err)
				}
				err = writeJSON(filepath.Join(root, "writer.json"), map[string]string{"key": "other"})
				release()
				if err != nil {
					t.Fatal(err)
				}
			case "changed input":
				records = append(records, map[string]any{"type": "user", "message": map[string]any{"content": "new input"}})
				writeReportRecords(t, path, records)
			}
			if err := writeJSON(life, state); err != nil {
				t.Fatal(err)
			}
			if _, err := s.ReconcileSession(t.Context(), spec.Key); err == nil {
				t.Fatal("uncertain scope settled")
			}
			if _, err := os.Stat(filepath.Join(dir, "result.json")); !os.IsNotExist(err) {
				t.Fatal("terminal result leaked")
			}
		})
	}
}

func TestClaudeInterruptedProviderRecoveryRevalidatesEvidenceAndExplicitClosure(t *testing.T) {
	s := testService(t)
	binding, transcript, _, _ := reportFixture(t)
	binding.ID, binding.Name, binding.PID = "old", "old", 1073741824
	binding.HostProof, binding.DirectoryProof = sessionHostProof(), sessionDirectoryProof(binding.Directory)
	binding.ProviderHome = os.Getenv("CLAUDE_CONFIG_DIR")
	binding.ProviderHomeProof = sessionDirectoryProof(binding.ProviderHome)
	binding.Scope = "/sys/fs/cgroup/roami-disposable-proof/tmux-spawn-00000000-0000-4000-8000-000000000001.scope"
	binding.Processes = map[int]string{binding.PID: "old-token"}
	if !providerStopped(binding) {
		t.Skip("saved scope/proc proof unavailable")
	}
	workspace, err := s.rememberWorkspace(Workspace{Directory: binding.Directory})
	if err != nil {
		t.Fatal(err)
	}
	prior := Spec{Key: "interrupted-prior", Executor: "claude", Persistent: true, Directory: binding.Directory, Prompt: "Retained work"}
	dir, _ := s.directory(prior.Key)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	turn := "turn"
	prompt := sessionPrompt(dir, prior)
	since := time.Now().UnixMilli()
	records := interruptedClaudeRecords(binding, prompt, turn, since, false)
	writeReportRecords(t, transcript, records)
	result, digest, _ := claudeInterruptedEvidence(binding, turn, workspaceHash(prompt), since)
	if result == nil {
		t.Fatal("fixture terminal absent")
	}
	result.InputStopped, result.OutcomeKnown, result.StopEvidence = boolPointer(true), boolPointer(true), digest
	if err := writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(filepath.Join(dir, "cancel.json"), map[string]bool{"cancel": true}); err != nil {
		t.Fatal(err)
	}
	intent := sessionInterrupt{ResourceID: binding.resourceID(), ProviderID: binding.ProviderID, TurnID: turn, PromptHash: workspaceHash(prompt), CreatedMS: since, Delivered: true}
	if err := writeJSON(filepath.Join(dir, "interrupt-request.json"), intent); err != nil {
		t.Fatal(err)
	}
	state := sessionLifecycle{Binding: binding, Executor: "claude", Workspace: &workspace, State: "idle", CompletedKey: prior.Key, TurnID: turn, PromptHash: workspaceHash(prompt), Tools: map[string]bool{}}
	source := providerRecoverySource{Spec: prior, Receipt: Receipt{Session: binding.ID, Workspace: &workspace, Binding: &binding}, Lifecycle: state}
	next := Spec{Key: "recovered", Executor: "claude", Persistent: true, SessionID: binding.ID, ResumeFrom: prior.Key, ResumeProvider: binding.ProviderID, Prompt: "Continue"}
	if got, err := s.providerRecovery(t.Context(), next, source); err != nil || got != workspace {
		t.Fatalf("original provider recovery: %+v %v", got, err)
	}
	records = append(records, map[string]any{"type": "mode"})
	writeReportRecords(t, transcript, records)
	if _, err := s.providerRecovery(t.Context(), next, source); err == nil {
		t.Fatal("changed evidence accepted")
	}
	late := map[string]any{"type": "assistant", "uuid": "late", "parentUuid": "interrupted", "sessionId": binding.ProviderID, "promptId": turn, "cwd": binding.Directory, "timestamp": time.Now().UTC().Format(time.RFC3339Nano), "message": map[string]any{"content": "Late final answer", "stop_reason": "end_turn"}}
	writeReportRecords(t, transcript, append(records[:len(records)-1], late))
	if claudeReportedProgress(binding, turn, workspaceHash(prompt), dir) == nil {
		t.Fatal("fixture must exercise progress fallback bypass")
	}
	if _, err := s.providerRecovery(t.Context(), next, source); err == nil {
		t.Fatal("later progress bypassed interrupted evidence")
	}
	writeReportRecords(t, transcript, records[:len(records)-1])
	if err := writeJSON(filepath.Join(dir, "closed.json"), map[string]bool{"closed": true}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.providerRecovery(t.Context(), next, source); err == nil || err.Error() != "SESSION_RECOVERY_EXPLICITLY_CLOSED" {
		t.Fatalf("explicit closure bypassed: %v", err)
	}
}
