package agentexecution

import (
	"context"
	"fmt"
	"path/filepath"
	"reflect"
	"time"
)

// Absence alone is insufficient: the entire original provider window must prove rejection.
func (s Service) reconcileMissingClaudeRejection(ctx context.Context, key, dir string, spec Spec, receipt Receipt, previous Result, hasResult bool) (Status, error) {
	empty := Status{}
	binding := *receipt.Binding
	if binding.HostProof == "" || !s.sessionExecutionMissing(binding) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_STOP_UNCONFIRMED")
	}
	path, err := s.lifecycleFile(binding)
	if err != nil {
		return empty, err
	}
	unlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return empty, err
	}
	defer unlock()
	var state sessionLifecycle
	if readJSON(path, &state) != nil || state.Executor != "claude" || state.Structured || state.ProviderConflict != nil || !reflect.DeepEqual(state.Binding, binding) || state.Workspace == nil || receipt.Workspace == nil || *state.Workspace != *receipt.Workspace || len(state.Tools) != 0 || state.PromptHash != workspaceHash(sessionPrompt(dir, spec)) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_BINDING_REQUIRED")
	}
	if hasResult && state.CompletedKey == key && state.LaunchKey == "" {
		receipt.State = previous.State
		return Status{Receipt: receipt, Result: &previous}, nil
	}
	if state.LaunchKey != key || state.State != "unknown" || (state.UnknownReason != "" && state.UnknownReason != "SESSION_PROMPT_MISMATCH" && state.UnknownReason != "SESSION_INTERRUPTED") {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	result, digest := claudeExplicitRejectionEvidence(binding, state.TurnID, state.PromptHash)
	if result == nil || (hasResult && previous.StopEvidence != digest) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_STOP_UNCONFIRMED")
	}
	if binding.Directory != receipt.Workspace.Directory || binding.DirectoryProof == "" || sessionDirectoryProof(binding.Directory) != binding.DirectoryProof || binding.ProviderHomeProof == "" || sessionDirectoryProof(binding.ProviderHome) != binding.ProviderHomeProof {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_WORKSPACE_REQUIRED")
	}
	root, release, err := s.lockWorkspaceWriter(ctx, binding.Directory)
	if err != nil {
		return empty, err
	}
	defer release()
	var writer struct {
		Key string `json:"key"`
	}
	if readJSON(filepath.Join(root, "writer.json"), &writer) != nil || (!hasResult && writer.Key != key) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_WORKSPACE_CHANGED")
	}
	checked, again := claudeExplicitRejectionEvidence(binding, state.TurnID, state.PromptHash)
	if checked == nil || again != digest || !s.sessionExecutionMissing(binding) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_EVIDENCE_CHANGED")
	}
	if err := ctx.Err(); err != nil {
		return empty, err
	}
	stopped := true
	result.State, result.Summary, result.InputStopped, result.OutcomeKnown, result.StopEvidence = "failed", "SESSION_SCOPE_CHANGED_STOPPED", &stopped, &stopped, digest
	if err := writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
		return empty, err
	}
	state.State, state.UnknownReason, state.LaunchKey, state.CompletedKey, state.EndedIdle = "idle", "", "", key, true
	state.UpdatedMS = time.Now().UnixMilli()
	if err := writeJSON(path, state); err != nil {
		return empty, err
	}
	receipt.State = "failed"
	return Status{Receipt: receipt, Result: result}, nil
}
