package agentexecution

import (
	"context"
	"fmt"
	"path/filepath"
	"time"
)

// Changed input is reconciled explicitly as failure, never as the old task's success.
func (s Service) reconcileClaudeChangedInput(ctx context.Context, key, dir, statePath string, spec Spec, receipt Receipt, binding SessionBinding, state *sessionLifecycle, previous Result, hasResult bool) (Status, error) {
	empty := Status{}
	if state.Executor != "claude" || state.Structured || state.State != "unknown" || (state.UnknownReason != "SESSION_PROMPT_MISMATCH" && state.UnknownReason != "") || state.ProviderConflict != nil || state.LaunchKey != key || len(state.Tools) != 0 || state.Binding.ProviderID != receipt.Binding.ProviderID || state.Binding.resourceID() != binding.resourceID() || state.Binding.PID != binding.PID || state.Binding.Directory != binding.Directory || state.PromptHash != workspaceHash(sessionPrompt(dir, spec)) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	result, digest := claudeRejectedWindow(state.Binding, state.TurnID, state.PromptHash, true)
	if result == nil || !sessionProcessesStopped(state.Binding) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_STOP_UNCONFIRMED")
	}
	if hasResult && previous.StopEvidence != digest {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_EVIDENCE_CHANGED")
	}
	if receipt.Workspace == nil || receipt.Workspace.Directory != binding.Directory {
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
	checked, again := claudeRejectedWindow(state.Binding, state.TurnID, state.PromptHash, true)
	if checked == nil || again != digest || !sessionProcessesStopped(state.Binding) {
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
	state.State, state.UnknownReason, state.LaunchKey, state.CompletedKey, state.EndedIdle = "idle", "", "", key, false
	state.UpdatedMS = time.Now().UnixMilli()
	if err := writeJSON(statePath, state); err != nil {
		return empty, err
	}
	receipt.State = "failed"
	return Status{Receipt: receipt, Result: result}, nil
}
