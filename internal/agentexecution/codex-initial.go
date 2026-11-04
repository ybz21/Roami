package agentexecution

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"time"

	sessmeta "github.com/ybz21/Roami/internal/sessionstore"
)

type codexInitialObservation struct {
	ObservedAtRecovery int64            `json:"observedAtRecovery"`
	Original           sessionLifecycle `json:"originalLifecycle"`
	Binding            SessionBinding   `json:"binding"`
	TurnID             string           `json:"turnId"`
	PromptHash         string           `json:"promptHash"`
	TranscriptSHA256   string           `json:"transcriptSha256"`
}

func (s Service) reconcileInitialCodex(key string, status Status) (Status, bool, error) {
	if status.Binding != nil || status.Workspace == nil || status.Session == "" {
		return status, false, nil
	}
	dir, _ := s.directory(key)
	var spec Spec
	if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || !spec.Persistent || spec.Executor != "codex" || spec.SessionID != "" || spec.Key != key {
		return status, false, nil
	}
	controlUnlock, err := lock(filepath.Join(dir, "initial-control.lock"))
	if err != nil {
		return status, false, err
	}
	defer controlUnlock()
	binding, err := s.paneBinding(status.Session, false)
	if err != nil || binding.ID != status.Session || binding.Directory != status.Workspace.Directory {
		return status, false, nil
	}
	path, err := s.lifecycleFile(binding)
	if err != nil {
		return status, false, err
	}
	unlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return status, false, err
	}
	defer unlock()
	originalReceipt := status.Receipt
	var state sessionLifecycle
	if readJSON(path, &state) != nil || !state.InitialLaunch || state.Structured || state.Executor != "codex" || state.LaunchKey != key || state.TurnID != "" || state.PromptHash != "" || len(state.Tools) != 0 || state.Binding.resourceID() != binding.resourceID() || state.Binding.PID != binding.PID || state.Binding.Directory != binding.Directory {
		return status, false, nil
	}
	unconfirmed := state.State == "unknown"
	if unconfirmed {
		status.State, status.ObservationErrorCode = "unknown", state.UnknownReason
		if status.ObservationErrorCode == "" {
			status.ObservationErrorCode = "SESSION_INITIAL_IDENTITY_UNCONFIRMED"
		}
	}
	marker, err := s.Runtime.TmuxOutput("display-message", "-p", "-t", binding.Pane, "#{ROAMI_AGENT_LAUNCH}")
	if err != nil || strings.TrimSpace(marker) != filepath.Base(dir) {
		return status, unconfirmed, nil
	}
	if _, err := os.Stat(filepath.Join(dir, "cancel.json")); !os.IsNotExist(err) {
		return status, unconfirmed, nil
	}
	prompt := sessionPrompt(dir, spec)
	info, err := os.Lstat(filepath.Join(dir, "prompt.txt"))
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0022 != 0 {
		return status, unconfirmed, nil
	}
	saved, err := os.ReadFile(filepath.Join(dir, "prompt.txt"))
	if err != nil || string(saved) != prompt {
		return status, unconfirmed, nil
	}
	completion := initialCodexCompletion(binding, workspaceHash(prompt))
	if completion == nil {
		return status, unconfirmed, nil
	}
	observed, ok := initialCodexProcesses(state.Binding, prompt, completion.CreatedMS, filepath.Base(dir))
	if !ok {
		return status, unconfirmed, nil
	}
	observed.ProviderID = completion.ProviderID
	current, err := s.paneBinding(status.Session, false)
	if err != nil || current.resourceID() != binding.resourceID() || current.PID != binding.PID || current.Directory != binding.Directory {
		return status, unconfirmed, nil
	}
	again, ok := initialCodexProcesses(observed, prompt, completion.CreatedMS, filepath.Base(dir))
	if !ok || !reflect.DeepEqual(observed.Processes, again.Processes) {
		return status, unconfirmed, nil
	}
	verified := initialCodexCompletion(current, workspaceHash(prompt))
	if verified == nil || verified.ProviderID != completion.ProviderID || verified.TurnID != completion.TurnID || verified.Proof != completion.Proof {
		return status, unconfirmed, nil
	}
	var finalSpec Spec
	var finalReceipt Receipt
	if readJSON(filepath.Join(dir, "spec.json"), &finalSpec) != nil || finalSpec != spec || readJSON(filepath.Join(dir, "receipt.json"), &finalReceipt) != nil || !reflect.DeepEqual(finalReceipt, originalReceipt) {
		return status, unconfirmed, nil
	}
	if _, err := os.Stat(filepath.Join(dir, "cancel.json")); !os.IsNotExist(err) {
		return status, unconfirmed, nil
	}
	// Audit the new observation before any terminal result can release the workspace writer.
	audit := codexInitialObservation{time.Now().UnixMilli(), state, observed, completion.TurnID, workspaceHash(prompt), completion.Proof}
	if err := writeJSON(filepath.Join(dir, "initial-recovery.json"), audit); err != nil {
		return status, false, err
	}
	status.Binding = &observed
	status.Receipt.State = "running"
	state.Binding, state.InitialLaunch, state.State, state.LaunchKey = observed, false, "idle", ""
	state.TurnID, state.PromptHash, state.UnknownReason = completion.TurnID, workspaceHash(prompt), ""
	state.UpdatedMS = time.Now().UnixMilli()
	if err := writeJSON(path, state); err != nil {
		return status, false, err
	}
	if err := writeJSON(filepath.Join(dir, "receipt.json"), status.Receipt); err != nil {
		return status, false, err
	}
	meta := sessmeta.New(s.Runtime.HomeDir)
	meta.DataDir = s.Runtime.DataDir
	if row, ok := meta.Get(binding.Name); ok && row.AgentKind == "codex" {
		if err := meta.SetAgentSession(binding.Name, observed.ProviderID); err != nil {
			return status, false, err
		}
	}
	stopped := true
	completion.Result.InputStopped, completion.Result.OutcomeKnown = &stopped, &stopped
	if err := writeJSON(filepath.Join(dir, "result.json"), completion.Result); err != nil {
		return status, false, err
	}
	status.State, status.Result, status.ObservationErrorCode = completion.Result.State, completion.Result, ""
	return status, true, nil
}
