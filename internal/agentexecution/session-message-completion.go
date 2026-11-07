package agentexecution

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// A direct message has no launch result; its original provider turn can still prove idle.
func (s Service) reconcileDirectCodexCompletion(binding SessionBinding, state *sessionLifecycle, path string) error {
	if state.Executor != "codex" || state.Structured || state.State != "busy" || state.LaunchKey != "" || state.InitialLaunch || state.UnknownReason != "" || len(state.Tools) != 0 || state.TurnID == "" || state.PromptHash == "" || state.Binding.ProviderID == "" || state.Binding.resourceID() != binding.resourceID() || state.Binding.PID != binding.PID || state.Binding.Directory != binding.Directory {
		return nil
	}
	result, evidence := codexCompletion(state.Binding, state.TurnID, state.PromptHash)
	if result == nil || result.State != "succeeded" || !sessionProcessesStopped(state.Binding) {
		return nil
	}
	proof := completionSource{state.Binding.ProviderID, state.TurnID, evidence, result.FinishedMS}
	directory := filepath.Join(filepath.Dir(path), "message-completions", workspaceHash(state.TurnID))
	if err := os.MkdirAll(directory, 0700); err != nil {
		return err
	}
	proofPath := filepath.Join(directory, "completion-source.json")
	var prior completionSource
	if err := readJSON(proofPath, &prior); errors.Is(err, os.ErrNotExist) {
		if err := writeJSON(proofPath, proof); err != nil {
			return err
		}
	} else if err != nil {
		return err
	} else if prior != proof {
		return fmt.Errorf("SESSION_COMPLETION_EVIDENCE_CHANGED")
	}
	state.State, state.EndedIdle, state.UpdatedMS = "idle", false, time.Now().UnixMilli()
	return writeJSON(path, state)
}
