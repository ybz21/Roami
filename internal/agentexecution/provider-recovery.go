package agentexecution

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"

	"github.com/ybz21/Roami/internal/agent"
	"github.com/ybz21/Roami/internal/memguard"
)

type providerRecoverySource struct {
	Spec      Spec             `json:"spec"`
	Receipt   Receipt          `json:"receipt"`
	Lifecycle sessionLifecycle `json:"lifecycle"`
}

func (s Service) recheckProviderRecovery(ctx context.Context, dir string, spec Spec) (providerRecoverySource, error) {
	var saved, current providerRecoverySource
	if readJSON(filepath.Join(dir, "provider-restore-source.json"), &saved) != nil || saved.Receipt.Binding == nil {
		return saved, fmt.Errorf("SESSION_RECOVERY_BINDING_CONFLICT")
	}
	priorDir, err := s.directory(spec.ResumeFrom)
	if err != nil {
		return saved, err
	}
	path, err := s.lifecycleFile(*saved.Receipt.Binding)
	if err != nil {
		return saved, err
	}
	unlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return saved, err
	}
	defer unlock()
	var claim Spec
	if readJSON(filepath.Join(filepath.Dir(path), "recovery-claim.json"), &claim) != nil || claim != spec || readJSON(filepath.Join(priorDir, "spec.json"), &current.Spec) != nil || readJSON(filepath.Join(priorDir, "receipt.json"), &current.Receipt) != nil || readJSON(path, &current.Lifecycle) != nil || !reflect.DeepEqual(current, saved) {
		return saved, fmt.Errorf("SESSION_RECOVERY_SOURCE_CHANGED")
	}
	if _, err := s.Runtime.ResolveStrict(spec.SessionID); err == nil || err.Error() != "SESSION_TARGET_NOT_FOUND" {
		return saved, fmt.Errorf("SESSION_RECOVERY_TARGET_OBSERVATION_FAILED")
	}
	_, err = s.providerRecovery(ctx, spec, current)
	return current, err
}

func (s Service) restoreProviderSession(ctx context.Context, dir string, spec Spec) (Status, error) {
	if spec.ResumeFrom == "" || spec.ResumeFrom == spec.Key || spec.ResumeProvider == "" {
		return Status{}, fmt.Errorf("INVALID_SESSION_EXECUTION_SPEC")
	}
	if _, err := s.Runtime.ResolveStrict(spec.SessionID); err == nil || err.Error() != "SESSION_TARGET_NOT_FOUND" {
		return Status{}, fmt.Errorf("SESSION_RECOVERY_TARGET_OBSERVATION_FAILED")
	}
	priorDir, err := s.directory(spec.ResumeFrom)
	if err != nil {
		return Status{}, err
	}
	var source providerRecoverySource
	if readJSON(filepath.Join(priorDir, "spec.json"), &source.Spec) != nil || readJSON(filepath.Join(priorDir, "receipt.json"), &source.Receipt) != nil || source.Receipt.Binding == nil {
		return Status{}, fmt.Errorf("SESSION_RECOVERY_BINDING_CONFLICT")
	}
	path, err := s.lifecycleFile(*source.Receipt.Binding)
	if err != nil {
		return Status{}, err
	}
	unlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return Status{}, err
	}
	defer unlock()
	if readJSON(path, &source.Lifecycle) != nil {
		return Status{}, fmt.Errorf("SESSION_LIFECYCLE_UNAVAILABLE")
	}
	workspace, err := s.providerRecovery(ctx, spec, source)
	if err != nil {
		return Status{}, err
	}
	claim := filepath.Join(filepath.Dir(path), "recovery-claim.json")
	previous, err := s.availableRecoveryClaim(claim, spec)
	if err != nil {
		return Status{}, err
	}
	if _, err := agent.ResolveBinary(spec.Executor); err != nil {
		return Status{}, err
	}
	root, release, err := s.lockWorkspaceWriter(ctx, workspace.Directory)
	if err != nil {
		return Status{}, err
	}
	defer release()
	if err := s.workspaceWriterReady(root); err != nil {
		return Status{}, err
	}
	if err := ctx.Err(); err != nil {
		return Status{}, err
	}
	if err := writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
		return Status{}, err
	}
	if err := writeJSON(filepath.Join(dir, "provider-restore-source.json"), source); err != nil {
		return Status{}, err
	}
	if previous != nil {
		if err := writeJSON(filepath.Join(dir, "provider-restore-prior-claim.json"), previous); err != nil {
			return Status{}, err
		}
	}
	if err := writeJSON(claim, spec); err != nil {
		return Status{}, err
	}
	receipt := Receipt{State: "starting", Workspace: &workspace, DeadlineMS: executionDeadline(spec.TimeoutSeconds)}
	if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		return Status{}, err
	}
	return s.startExecutionSession(ctx, dir, spec, receipt)
}

func (s Service) availableRecoveryClaim(path string, spec Spec) (*Spec, error) {
	var prior Spec
	if err := readJSON(path, &prior); errors.Is(err, os.ErrNotExist) {
		return nil, nil
	} else if err != nil || prior.Key == spec.Key || prior.ResumeFrom != spec.ResumeFrom || prior.ResumeProvider != spec.ResumeProvider || prior.SessionID != spec.SessionID || prior.Executor != spec.Executor {
		return nil, fmt.Errorf("SESSION_RECOVERY_ALREADY_CLAIMED")
	}
	dir, err := s.directory(prior.Key)
	var stored Spec
	var receipt Receipt
	var result Result
	if err != nil || readJSON(filepath.Join(dir, "spec.json"), &stored) != nil || stored != prior || readJSON(filepath.Join(dir, "receipt.json"), &receipt) != nil || receipt.Binding != nil || readJSON(filepath.Join(dir, "result.json"), &result) != nil || result.State != "failed" || result.ExecutionStarted == nil || *result.ExecutionStarted || result.ExitCodeSource != "not_started" || result.InputStopped == nil || !*result.InputStopped || result.OutcomeKnown == nil || !*result.OutcomeKnown {
		return nil, fmt.Errorf("SESSION_RECOVERY_ALREADY_CLAIMED")
	}
	if _, err := s.Runtime.ResolveStrict(receipt.Session); receipt.Session == "" || err == nil || err.Error() != "SESSION_TARGET_NOT_FOUND" {
		return nil, fmt.Errorf("SESSION_RECOVERY_ALREADY_CLAIMED")
	}
	return &prior, nil
}

func (s Service) recoveryWorkspace(ctx context.Context, saved Workspace) (Workspace, error) {
	directory, err := canonicalWorkspace(saved.Directory)
	if err != nil || directory != saved.Directory || saved.ID != workspaceHash(saved.ProjectID+"\x00"+directory) {
		return Workspace{}, fmt.Errorf("SESSION_RECOVERY_WORKSPACE_CHANGED")
	}
	var registered Workspace
	if readJSON(filepath.Join(s.Runtime.DataDir, "agents", "workspaces", saved.ID+".json"), &registered) != nil || registered != saved {
		return Workspace{}, fmt.Errorf("SESSION_RECOVERY_WORKSPACE_CHANGED")
	}
	if saved.ProjectID != "" {
		return s.reuseWorkspace(ctx, Spec{ProjectID: saved.ProjectID, WorkspaceID: saved.ID})
	}
	return saved, nil
}

func providerProcessesGone(binding SessionBinding, snapshot map[int]paneProcess, scoped []int) bool {
	if binding.PID < 1 || binding.Processes[binding.PID] == "" || len(scoped) != 0 {
		return false
	}
	for pid, token := range binding.Processes {
		if token == "" || snapshot[pid].Token == token {
			return false
		}
	}
	return true
}

func providerStopped(binding SessionBinding) bool {
	if binding.HostProof == "" || binding.HostProof != sessionHostProof() || binding.Scope == "" {
		return false
	}
	scoped, err := memguard.RecordedScopeProcesses(binding.Scope)
	if err != nil {
		return false
	}
	snapshot, err := processSnapshot()
	return err == nil && providerProcessesGone(binding, snapshot, scoped)
}

// The caller holds the original lifecycle lock until it records the recovery claim.
func (s Service) providerRecovery(ctx context.Context, spec Spec, source providerRecoverySource) (Workspace, error) {
	prior, receipt, state := source.Spec, source.Receipt, source.Lifecycle
	if spec.ResumeFrom == "" || spec.ResumeFrom == spec.Key || prior.Key != spec.ResumeFrom || !spec.Persistent || !prior.Persistent || prior.Executor != spec.Executor || (spec.Executor != "codex" && spec.Executor != "claude") || receipt.Binding == nil || receipt.Workspace == nil || spec.SessionID != receipt.Session || receipt.Binding.ID != receipt.Session || !codexThreadID.MatchString(spec.ResumeProvider) || receipt.Binding.ProviderID != spec.ResumeProvider {
		return Workspace{}, fmt.Errorf("SESSION_RECOVERY_BINDING_CONFLICT")
	}
	binding := *receipt.Binding
	if !reflect.DeepEqual(state.Binding, binding) || state.Workspace == nil || *state.Workspace != *receipt.Workspace || state.Executor != spec.Executor || state.InitialLaunch || state.Structured || state.CompletedKey != spec.ResumeFrom || state.LaunchKey != "" || state.TurnID == "" || len(state.Tools) != 0 || (state.State != "idle" && !(state.State == "unknown" && state.EndedIdle && state.UnknownReason == "SESSION_INTERRUPTED")) {
		return Workspace{}, fmt.Errorf("SESSION_RECOVERY_SOURCE_CHANGED")
	}
	dir, err := s.directory(spec.ResumeFrom)
	if err != nil || state.PromptHash != workspaceHash(sessionPrompt(dir, prior)) {
		return Workspace{}, fmt.Errorf("SESSION_RECOVERY_SOURCE_CHANGED")
	}
	for _, path := range []string{filepath.Join(dir, "closed.json"), filepath.Join(s.Runtime.DataDir, "agents", "closed-sessions", binding.resourceID()+".json")} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			return Workspace{}, fmt.Errorf("SESSION_RECOVERY_EXPLICITLY_CLOSED")
		}
	}
	var result Result
	if readJSON(filepath.Join(dir, "result.json"), &result) != nil || result.InputStopped == nil || !*result.InputStopped || result.OutcomeKnown == nil || !*result.OutcomeKnown || (result.State != "succeeded" && result.State != "failed" && result.State != "cancelled") {
		return Workspace{}, fmt.Errorf("SESSION_RECOVERY_OUTCOME_UNRESOLVED")
	}
	if binding.DirectoryProof == "" || sessionDirectoryProof(binding.Directory) != binding.DirectoryProof || binding.Directory != receipt.Workspace.Directory || !providerStopped(binding) {
		return Workspace{}, fmt.Errorf("SESSION_RECOVERY_STOP_UNCONFIRMED")
	}
	if binding.ProviderHome == "" || binding.ProviderHomeProof == "" || sessionDirectoryProof(binding.ProviderHome) != binding.ProviderHomeProof {
		return Workspace{}, fmt.Errorf("SESSION_RECOVERY_TRANSCRIPT_UNAVAILABLE")
	}
	if spec.Executor == "codex" {
		if result, _ := codexOutcome(binding, state.TurnID, state.PromptHash, result.State == "cancelled"); result == nil {
			return Workspace{}, fmt.Errorf("SESSION_RECOVERY_TRANSCRIPT_UNAVAILABLE")
		}
	} else if progress := claudeReportedProgress(binding, state.TurnID, state.PromptHash, dir); progress == nil || progress.Directory != binding.Directory {
		return Workspace{}, fmt.Errorf("SESSION_RECOVERY_TRANSCRIPT_UNAVAILABLE")
	}
	return s.recoveryWorkspace(ctx, *receipt.Workspace)
}
