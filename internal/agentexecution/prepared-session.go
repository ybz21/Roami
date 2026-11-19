package agentexecution

import (
	"fmt"
	"path/filepath"
	"reflect"
	"regexp"
)

type PreparedSession struct {
	LaunchKey       string                `json:"launchKey"`
	SessionID       string                `json:"sessionId"`
	Executor        string                `json:"executor"`
	ConfiguredModel string                `json:"configuredModel"`
	Binding         SessionBinding        `json:"sessionBinding"`
	Workspace       Workspace             `json:"workspace"`
	Ready           bool                  `json:"ready"`
	RouteRefusal    *PreparedRouteRefusal `json:"routeRefusal,omitempty"`
}

type PreparedRouteRefusal struct {
	LaunchKey    string `json:"launchKey"`
	Code         string `json:"code"`
	StopEvidence string `json:"stopEvidenceSha256"`
	FinishedMS   int64  `json:"finishedMs"`
}

var projectMainLaunchKey = regexp.MustCompile(`^project-main:[a-f0-9]{32}:[a-f0-9]{24}(:retry-[1-9][0-9]{0,18})?$`)
var routeRefusalDigest = regexp.MustCompile(`^[a-f0-9]{64}$`)

func samePreparedProvider(a, b SessionBinding) bool {
	if a.PID <= 0 || a.Processes[a.PID] == "" || a.Processes[a.PID] != b.Processes[b.PID] {
		return false
	}
	a.Processes, b.Processes = nil, nil
	a.ForeignProcesses, b.ForeignProcesses = nil, nil
	return reflect.DeepEqual(a, b)
}

type preparedTurnProof struct {
	Spec       Spec
	Receipt    Receipt
	Result     Result
	NativeIdle bool
}

func preparedTurnMatches(state sessionLifecycle, proof preparedTurnProof) bool {
	r := proof.Result
	return state.CompletedKey != "" && proof.Spec.Key == state.CompletedKey && proof.Spec.SessionID == state.Binding.ID && proof.Spec.Executor == state.Executor && proof.Spec.Model == "" && proof.Receipt.Session == state.Binding.ID && proof.Receipt.Binding != nil && reflect.DeepEqual(*proof.Receipt.Binding, state.Binding) && proof.Receipt.Workspace != nil && proof.Receipt.Workspace.Directory == state.Binding.Directory && (r.State == "succeeded" || r.State == "failed" || r.State == "cancelled") && r.InputStopped != nil && *r.InputStopped && r.OutcomeKnown != nil && *r.OutcomeKnown
}

func preparedSelection(key string, spec Spec, receipt Receipt, state sessionLifecycle, result Result, later ...preparedTurnProof) (PreparedSession, error) {
	settledKey := key
	if state.CompletedKey != key {
		if len(later) != 1 || !(state.CompletedKey == "" && later[0].NativeIdle || preparedTurnMatches(state, later[0])) {
			return PreparedSession{}, fmt.Errorf("SESSION_PREPARATION_UNCONFIRMED")
		}
		settledKey = state.CompletedKey
	}

	if spec.Key != key || !spec.Persistent || spec.SessionID != "" || spec.Executor == "" || spec.Model == "" || receipt.Binding == nil || receipt.Workspace == nil || receipt.Session != state.Binding.ID || state.State != "idle" || state.LaunchKey != "" || state.CompletedKey != settledKey || state.UnknownReason != "" || state.ProviderConflict != nil || state.EndedIdle || len(state.Tools) != 0 || state.Executor != spec.Executor || state.Model != spec.Model || !samePreparedProvider(*receipt.Binding, state.Binding) || receipt.Workspace.Directory != state.Binding.Directory || result.State != "succeeded" || result.InputStopped == nil || !*result.InputStopped || result.OutcomeKnown == nil || !*result.OutcomeKnown {
		return PreparedSession{}, fmt.Errorf("SESSION_PREPARATION_UNCONFIRMED")
	}
	selected := PreparedSession{LaunchKey: key, SessionID: receipt.Session, Executor: spec.Executor, ConfiguredModel: state.Model, Binding: state.Binding, Workspace: *receipt.Workspace, Ready: true}
	if spec.Executor == "claude" && settledKey != key && settledKey != "" && later[0].Spec.Persistent &&
		later[0].Spec.PreparedFrom == key && projectMainLaunchKey.MatchString(settledKey) {
		r := later[0].Result
		if r.State == "failed" && r.FinishedMS > 0 && routeRefusalDigest.MatchString(r.StopEvidence) &&
			(r.ErrorCode == "MODEL_ROUTE_NO_AVAILABLE_MEMBER" || r.ErrorCode == "CLAUDE_COMPACTION_FAILED") {
			selected.RouteRefusal = &PreparedRouteRefusal{LaunchKey: settledKey, Code: r.ErrorCode, FinishedMS: r.FinishedMS, StopEvidence: r.StopEvidence}
		}
	}
	return selected, nil
}

// Preserve the original provider while checking its latest settled turn.
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
	if normalized, _, ok := s.provenClaudeModelIdle(state); ok {
		state = normalized
	}
	var later []preparedTurnProof
	if state.CompletedKey == "" && (provenClaudeNativeIdle(state) || confirmedDirectClaudeIdle(binding, state, path)) {
		later = append(later, preparedTurnProof{NativeIdle: true})
	}
	if state.CompletedKey != key && state.CompletedKey != "" {
		latestDir, problem := s.directory(state.CompletedKey)
		if problem != nil {
			return PreparedSession{}, fmt.Errorf("SESSION_PREPARATION_UNCONFIRMED")
		}
		var current preparedTurnProof
		if readJSON(filepath.Join(latestDir, "spec.json"), &current.Spec) != nil || readJSON(filepath.Join(latestDir, "receipt.json"), &current.Receipt) != nil || readJSON(filepath.Join(latestDir, "result.json"), &current.Result) != nil {
			return PreparedSession{}, fmt.Errorf("SESSION_PREPARATION_UNCONFIRMED")
		}
		later = append(later, current)
	}
	selected, err := preparedSelection(key, spec, receipt, state, result, later...)
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
	return current.PreparedFrom != "" && initial.Key == current.PreparedFrom && initial.Persistent && initial.SessionID == "" && initial.Model != "" && initial.Executor == current.Executor && state.Executor == initial.Executor && state.Model == initial.Model && receipt.Binding != nil && receipt.Workspace != nil && receipt.Session == current.SessionID && samePreparedProvider(*receipt.Binding, state.Binding) && receipt.Workspace.Directory == state.Binding.Directory && result.State == "succeeded" && result.InputStopped != nil && *result.InputStopped && result.OutcomeKnown != nil && *result.OutcomeKnown
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
