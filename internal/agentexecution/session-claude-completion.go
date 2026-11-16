package agentexecution

import (
	"os"
	"path/filepath"
	"time"
)

// A matched Stop/idle pair may arrive before the final child process exits.
func (s Service) reconcileClaudeCompletion(key string, status Status, state *sessionLifecycle, statePath string, explicit bool) (Status, bool, error) {
	if state.Executor != "claude" || state.Structured || state.State != "unknown" || state.UnknownReason != "SESSION_STOP_UNCONFIRMED" || state.ProviderConflict != nil || state.LaunchKey != key || len(state.Tools) != 0 || state.Binding.ProviderID != status.Binding.ProviderID || state.Binding.resourceID() != status.Binding.resourceID() || state.Binding.PID != status.Binding.PID || state.Binding.Directory != status.Binding.Directory {
		return status, false, nil
	}
	candidate := state.ClaudeStop
	matched := candidate != nil && candidate.Idle && candidate.PromptID == state.TurnID && candidate.PromptHash == state.PromptHash
	if !matched && (!explicit || candidate != nil) {
		return status, false, nil
	}
	dir, _ := s.directory(key)
	var spec Spec
	if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || spec.Executor != "claude" || workspaceHash(sessionPrompt(dir, spec)) != state.PromptHash {
		return status, false, nil
	}
	var summary, digest string
	if matched {
		summary = candidate.Summary
		digest = workspaceHash(key + "\x00" + state.Binding.ProviderID + "\x00" + candidate.PromptID + "\x00" + candidate.PromptHash + "\x00" + summary)
	} else {
		// Older hosts retained the matched-idle reason, but discarded its summary.
		progress := claudeReportedProgress(state.Binding, state.TurnID, state.PromptHash, dir)
		if progress == nil || progress.ObservedMS > state.UpdatedMS || !sessionProcessesStopped(state.Binding) {
			return status, false, nil
		}
		checked := claudeReportedProgress(state.Binding, state.TurnID, state.PromptHash, dir)
		if checked == nil || checked.SourceDigest != progress.SourceDigest {
			return status, false, nil
		}
		summary, digest = progress.Summary, progress.SourceDigest
	}
	if !sessionProcessesStopped(state.Binding) {
		return status, false, nil
	}
	stopped := true
	result := &Result{State: "succeeded", Summary: summary, FinishedMS: state.UpdatedMS, InputStopped: &stopped, OutcomeKnown: &stopped, StopEvidence: digest}
	if _, err := os.Stat(filepath.Join(dir, "cancel.json")); err == nil {
		result.State = "cancelled"
	}
	if err := writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
		return status, false, err
	}
	state.State, state.LaunchKey, state.UnknownReason, state.CompletedKey = "idle", "", "", key
	state.ClaudeStop = nil
	state.UpdatedMS = time.Now().UnixMilli()
	if err := writeJSON(statePath, state); err != nil {
		return status, false, err
	}
	status.State, status.Result, status.Progress, status.ObservationErrorCode = result.State, result, nil, ""
	return status, true, nil
}
