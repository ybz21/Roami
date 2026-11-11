package agentexecution

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

type claudeRejectionInterrupt struct {
	ResourceID string         `json:"resourceId"`
	ProviderID string         `json:"providerConversationId"`
	TurnID     string         `json:"turnId"`
	PromptHash string         `json:"promptHash"`
	Evidence   string         `json:"evidence"`
	Processes  map[int]string `json:"processes"`
	Signalled  bool           `json:"signalled"`
}

// A proven rejection permits cancellation of owned descendants, not a stopped outcome.
func (s Service) cancelRejectedClaude(key string, status Status) (Status, bool, error) {
	if status.Binding == nil {
		return status, false, nil
	}
	dir, _ := s.directory(key)
	var spec Spec
	if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || spec.Key != key || spec.Executor != "claude" {
		return status, false, nil
	}
	binding, err := s.paneBinding(status.Binding.Name, false)
	if err != nil || binding.resourceID() != status.Binding.resourceID() || binding.PID != status.Binding.PID || binding.Directory != status.Binding.Directory {
		return status, false, nil
	}
	path, err := s.lifecycleFile(binding)
	if err != nil {
		return status, true, err
	}
	unlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return status, true, err
	}
	defer unlock()
	var state sessionLifecycle
	if readJSON(path, &state) != nil || state.Executor != "claude" || state.Structured || state.State != "unknown" || (state.UnknownReason != "" && state.UnknownReason != "SESSION_PROMPT_MISMATCH") || state.ProviderConflict != nil || state.LaunchKey != key || len(state.Tools) != 0 || state.Binding.ProviderID != status.Binding.ProviderID || state.Binding.resourceID() != binding.resourceID() || state.Binding.PID != binding.PID || state.Binding.Directory != binding.Directory || state.PromptHash != workspaceHash(sessionPrompt(dir, spec)) {
		return status, false, nil
	}
	observe := func() (*Result, string) {
		return claudeExplicitRejectionEvidence(state.Binding, state.TurnID, state.PromptHash)
	}
	result, digest := observe()
	if result == nil {
		return status, false, nil
	}
	snapshot, scope, scoped, err := paneProcessSnapshot(binding.PID)
	if err != nil || scope != state.Binding.Scope || snapshot[binding.PID].Token != state.Binding.Processes[binding.PID] {
		return status, false, nil
	}
	processes := capturedSessionTools(state.Binding, snapshot, scoped)
	request := claudeRejectionInterrupt{ResourceID: binding.resourceID(), ProviderID: state.Binding.ProviderID, TurnID: state.TurnID, PromptHash: state.PromptHash, Evidence: digest, Processes: processes}
	journal := filepath.Join(dir, "rejection-interrupt.json")
	var previous claudeRejectionInterrupt
	if err := readJSON(journal, &previous); err == nil {
		if previous.ResourceID != request.ResourceID || previous.ProviderID != request.ProviderID || previous.TurnID != request.TurnID || previous.PromptHash != request.PromptHash || previous.Evidence != request.Evidence {
			return status, true, fmt.Errorf("SESSION_INTERRUPT_CONFLICT")
		}
		if !previous.Signalled {
			status.ObservationErrorCode = "SESSION_TOOL_INTERRUPT_UNKNOWN"
			return status, true, nil
		}
		status.State = "cancelling"
		return status, true, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return status, true, err
	}
	if len(processes) == 0 {
		return status, false, nil
	}
	if err := writeJSON(journal, request); err != nil {
		return status, true, err
	}
	checked, again := observe()
	current, err := s.paneBinding(binding.Name, false)
	if checked == nil || again != digest || err != nil || current.resourceID() != binding.resourceID() || current.PID != binding.PID || current.Directory != binding.Directory {
		status.ObservationErrorCode = "SESSION_INTERRUPT_UNKNOWN"
		return status, true, nil
	}
	if err := signalCapturedSessionTools(state.Binding, processes); err != nil {
		status.ObservationErrorCode = "SESSION_TOOL_INTERRUPT_UNKNOWN"
		return status, true, nil
	}
	request.Signalled = true
	if err := writeJSON(journal, request); err != nil {
		return status, true, err
	}
	status.State, status.ObservationErrorCode = "cancelling", ""
	return status, true, nil
}
