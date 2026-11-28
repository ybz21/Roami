package agentexecution

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

func directClaudeCompletion(binding SessionBinding, state sessionLifecycle) (completionSource, bool) {
	if state.Executor != "claude" || state.Structured || state.InitialLaunch ||
		state.UnknownReason != "" || state.ProviderConflict != nil || state.EndedIdle ||
		state.LaunchKey != "" || state.CompletedKey != "" ||
		state.Binding.ProviderID == "" || state.claudeTranscriptModel() == "" ||
		binding.resourceID() != state.Binding.resourceID() || binding.PID != state.Binding.PID ||
		binding.Directory != state.Binding.Directory {
		return completionSource{}, false
	}
	// The direct input has no launch timestamp. Its exact hook prompt ID and hash select the root.
	result, digest, tools := claudeCompletedEvidenceForModel(state.Binding, state.TurnID, state.PromptHash, 1, state.claudeTranscriptModel())
	if result == nil || !sessionProcessesStopped(state.Binding) {
		return completionSource{}, false
	}
	for tool := range state.Tools {
		if tools[tool] == 0 {
			return completionSource{}, false
		}
	}
	return completionSource{state.Binding.ProviderID, state.TurnID, digest, result.FinishedMS}, true
}

func directClaudeCompletionPath(path, turn string) string {
	return filepath.Join(filepath.Dir(path), "message-completions", workspaceHash(turn), "completion-source.json")
}

func confirmedDirectClaudeIdle(binding SessionBinding, state sessionLifecycle, path string) bool {
	if state.State != "idle" || len(state.Tools) != 0 || state.TurnID == "" {
		return false
	}
	var saved completionSource
	if readJSON(directClaudeCompletionPath(path, state.TurnID), &saved) != nil {
		return false
	}
	actual, ok := directClaudeCompletion(binding, state)
	return ok && actual == saved
}

func reconcileDirectClaudeCompletion(ctx context.Context, binding SessionBinding, state *sessionLifecycle, path string) (bool, error) {
	if state.State != "unknown" || len(state.Tools) == 0 {
		return false, nil
	}
	proof, ok := directClaudeCompletion(binding, *state)
	if !ok {
		return false, nil
	}
	checked, ok := directClaudeCompletion(binding, *state)
	if !ok || checked != proof {
		return false, fmt.Errorf("SESSION_COMPLETION_EVIDENCE_CHANGED")
	}
	if err := ctx.Err(); err != nil {
		return false, err
	}
	proofPath := directClaudeCompletionPath(path, state.TurnID)
	if err := os.MkdirAll(filepath.Dir(proofPath), 0700); err != nil {
		return false, err
	}
	var previous completionSource
	if err := readJSON(proofPath, &previous); errors.Is(err, os.ErrNotExist) {
		if err = writeJSON(proofPath, proof); err != nil {
			return false, err
		}
	} else if err != nil {
		return false, err
	} else if previous != proof {
		return false, fmt.Errorf("SESSION_COMPLETION_EVIDENCE_CHANGED")
	}
	state.State, state.Tools, state.ClaudeStop = "idle", map[string]bool{}, nil
	state.UpdatedMS = time.Now().UnixMilli()
	return true, writeJSON(path, state)
}
