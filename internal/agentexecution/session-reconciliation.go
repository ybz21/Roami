package agentexecution

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// ReconcileSession settles changed input as failure using the provider's terminal record.
func (s Service) ReconcileSession(ctx context.Context, key string) (Status, error) {
	empty := Status{}
	dir, err := s.directory(key)
	if err != nil {
		return empty, err
	}
	unlock, err := lock(filepath.Join(dir, "launch.lock"))
	if err != nil {
		return empty, err
	}
	defer unlock()
	var spec Spec
	var receipt Receipt
	if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || spec.Key != key || spec.Executor != "codex" || readJSON(filepath.Join(dir, "receipt.json"), &receipt) != nil || receipt.Binding == nil || receipt.Binding.ProviderID == "" {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_BINDING_REQUIRED")
	}
	var previous Result
	hasResult := false
	if err = readJSON(filepath.Join(dir, "result.json"), &previous); err == nil {
		if previous.Summary != "SESSION_SCOPE_CHANGED_STOPPED" || previous.InputStopped == nil || !*previous.InputStopped || previous.OutcomeKnown == nil || !*previous.OutcomeKnown || previous.State != "failed" || !nativeEvidenceDigest.MatchString(previous.StopEvidence) {
			return empty, fmt.Errorf("SESSION_RECONCILIATION_RESULT_CONFLICT")
		}
		hasResult = true
	} else if !errors.Is(err, os.ErrNotExist) {
		return empty, err
	}
	binding, err := s.paneBinding(receipt.Binding.Name, false)
	if err != nil || binding.resourceID() != receipt.Binding.resourceID() || binding.PID != receipt.Binding.PID || binding.Directory != receipt.Binding.Directory {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_BINDING_CHANGED")
	}
	path, err := s.lifecycleFile(binding)
	if err != nil {
		return empty, err
	}
	stateUnlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return empty, err
	}
	defer stateUnlock()
	var state sessionLifecycle
	if err = readJSON(path, &state); err != nil {
		return empty, err
	}
	if hasResult && state.LaunchKey != key {
		receipt.State = "failed"
		return Status{Receipt: receipt, Result: &previous}, nil
	}
	if state.Executor != "codex" || state.State != "unknown" || state.UnknownReason != "SESSION_PROMPT_MISMATCH" || state.LaunchKey != key || state.ProviderConflict != nil || state.Binding.ProviderID != receipt.Binding.ProviderID || state.Binding.resourceID() != binding.resourceID() || state.Binding.PID != binding.PID || state.Binding.Directory != binding.Directory || state.PromptHash != workspaceHash(sessionPrompt(dir, spec)) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	if err = ctx.Err(); err != nil {
		return empty, err
	}
	result, evidence, commands := codexObservedTerminal(state.Binding, state.TurnID, state.PromptHash, false, false, true)
	if result == nil || !sessionProcessesStopped(state.Binding) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_STOP_UNCONFIRMED")
	}
	if hasResult && previous.StopEvidence != evidence {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_EVIDENCE_CHANGED")
	}
	for tool := range state.Tools {
		if strings.HasPrefix(tool, "subagent:") || commands[tool] <= 0 || commands[tool] > result.FinishedMS {
			return empty, fmt.Errorf("SESSION_RECONCILIATION_STOP_UNCONFIRMED")
		}
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
	if readJSON(filepath.Join(root, "writer.json"), &writer) != nil || !hasResult && writer.Key != key {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_WORKSPACE_CHANGED")
	}
	checked, latest, _ := codexObservedTerminal(state.Binding, state.TurnID, state.PromptHash, false, false, true)
	if checked == nil || latest != evidence || !sessionProcessesStopped(state.Binding) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_EVIDENCE_CHANGED")
	}
	if err = ctx.Err(); err != nil {
		return empty, err
	}
	stopped := true
	result.InputStopped, result.OutcomeKnown, result.StopEvidence = &stopped, &stopped, evidence
	if err = writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
		return empty, err
	}
	state.State, state.UnknownReason, state.LaunchKey = "idle", "", ""
	state.CompletedKey, state.Tools, state.EndedIdle = key, map[string]bool{}, false
	state.UpdatedMS = time.Now().UnixMilli()
	if err = writeJSON(path, state); err != nil {
		return empty, err
	}
	receipt.State = "failed"
	return Status{Receipt: receipt, Result: result}, nil
}
