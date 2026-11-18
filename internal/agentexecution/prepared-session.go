package agentexecution

import (
	"fmt"
	"path/filepath"
	"reflect"
)

type PreparedSession struct {
	LaunchKey       string         `json:"launchKey"`
	SessionID       string         `json:"sessionId"`
	Executor        string         `json:"executor"`
	ConfiguredModel string         `json:"configuredModel"`
	Binding         SessionBinding `json:"sessionBinding"`
	Workspace       Workspace      `json:"workspace"`
	Ready           bool           `json:"ready"`
}

func preparedSelection(key string, spec Spec, receipt Receipt, state sessionLifecycle, result Result) (PreparedSession, error) {
	if spec.Key != key || !spec.Persistent || spec.SessionID != "" || spec.Executor == "" || spec.Model == "" || receipt.Binding == nil || receipt.Workspace == nil || receipt.Session != state.Binding.ID || state.State != "idle" || state.LaunchKey != "" || state.CompletedKey != key || len(state.Tools) != 0 || state.Executor != spec.Executor || state.Model != spec.Model || !reflect.DeepEqual(state.Binding, *receipt.Binding) || receipt.Workspace.Directory != state.Binding.Directory || result.State != "succeeded" || result.InputStopped == nil || !*result.InputStopped || result.OutcomeKnown == nil || !*result.OutcomeKnown {
		return PreparedSession{}, fmt.Errorf("SESSION_PREPARATION_UNCONFIRMED")
	}
	return PreparedSession{LaunchKey: key, SessionID: receipt.Session, Executor: spec.Executor, ConfiguredModel: state.Model, Binding: state.Binding, Workspace: *receipt.Workspace, Ready: true}, nil
}

// Preparation identifies a stopped initial turn; it never grants a new task or replays input.
func (s Service) PreparedSession(key string) (PreparedSession, error) {
	dir, err := s.directory(key)
	if err != nil {
		return PreparedSession{}, err
	}
	var spec Spec
	var receipt Receipt
	var result Result
	if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || readJSON(filepath.Join(dir, "receipt.json"), &receipt) != nil || readJSON(filepath.Join(dir, "result.json"), &result) != nil || receipt.Binding == nil {
		return PreparedSession{}, fmt.Errorf("SESSION_PREPARATION_UNCONFIRMED")
	}
	binding, err := s.paneBinding(receipt.Session, false)
	if err != nil || binding.resourceID() != receipt.Binding.resourceID() {
		return PreparedSession{}, fmt.Errorf("SESSION_BINDING_UNAVAILABLE")
	}
	path, err := s.lifecycleFile(binding)
	if err != nil {
		return PreparedSession{}, err
	}
	unlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return PreparedSession{}, err
	}
	defer unlock()
	var state sessionLifecycle
	if readJSON(path, &state) != nil {
		return PreparedSession{}, fmt.Errorf("SESSION_LIFECYCLE_UNAVAILABLE")
	}
	selected, err := preparedSelection(key, spec, receipt, state, result)
	if err != nil {
		return PreparedSession{}, err
	}
	if !sessionProcessesStopped(state.Binding) {
		return PreparedSession{}, fmt.Errorf("SESSION_NOT_IDLE")
	}
	again, err := s.paneBinding(receipt.Session, false)
	if err != nil || again.resourceID() != binding.resourceID() || again.PID != binding.PID || again.Directory != binding.Directory {
		return PreparedSession{}, fmt.Errorf("SESSION_BINDING_UNAVAILABLE")
	}
	return selected, nil
}

func preparedOriginMatches(current Spec, state sessionLifecycle, initial Spec, receipt Receipt, result Result) bool {
	return current.PreparedFrom != "" && initial.Key == current.PreparedFrom && initial.Persistent && initial.SessionID == "" && initial.Model != "" && initial.Executor == current.Executor && state.Executor == initial.Executor && state.Model == initial.Model && receipt.Binding != nil && receipt.Workspace != nil && receipt.Session == current.SessionID && reflect.DeepEqual(*receipt.Binding, state.Binding) && receipt.Workspace.Directory == state.Binding.Directory && result.State == "succeeded" && result.InputStopped != nil && *result.InputStopped && result.OutcomeKnown != nil && *result.OutcomeKnown
}

// A later task must not silently attach to a restarted provider under the same label.
func (s Service) preparedContinuation(current Spec, state sessionLifecycle) error {
	dir, err := s.directory(current.PreparedFrom)
	if err != nil {
		return fmt.Errorf("SESSION_PROVIDER_BINDING_CHANGED")
	}
	var initial Spec
	var receipt Receipt
	var result Result
	if readJSON(filepath.Join(dir, "spec.json"), &initial) != nil || readJSON(filepath.Join(dir, "receipt.json"), &receipt) != nil || readJSON(filepath.Join(dir, "result.json"), &result) != nil || !preparedOriginMatches(current, state, initial, receipt, result) {
		return fmt.Errorf("SESSION_PROVIDER_BINDING_CHANGED")
	}
	return nil
}
