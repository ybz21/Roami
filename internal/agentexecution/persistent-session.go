package agentexecution

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"time"

	"github.com/ybz21/Roami/internal/application"
	"github.com/ybz21/Roami/internal/cli/spawn"
	"github.com/ybz21/Roami/internal/gitcontext"
	sessmeta "github.com/ybz21/Roami/internal/sessionstore"
)

func (s Service) runPersistent(ctx context.Context, dir string, spec Spec) error {
	var receipt Receipt
	if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
		return err
	}
	if receipt.Workspace == nil || receipt.Session == "" {
		return fmt.Errorf("SESSION_WORKSPACE_REQUIRED")
	}
	binding, err := s.paneBinding(receipt.Session, false)
	if err != nil {
		return err
	}
	ac := spawn.DefaultAgentConfig(receipt.Workspace.Directory)
	ac.Kind, ac.Interactive, ac.Model, ac.Permission = spec.Executor, true, spec.Model, spec.Permission
	if spec.ResumeFrom != "" {
		source, problem := s.recheckProviderRecovery(ctx, dir, spec)
		if problem != nil {
			return s.failPersistent(dir, problem)
		}
		ac.Model, ac.Permission = source.Lifecycle.Model, source.Lifecycle.Permission
		ac.SessionUUID = spec.ResumeProvider
		binding.ProviderID = spec.ResumeProvider
		binding.ProviderHome, binding.ProviderHomeProof = source.Receipt.Binding.ProviderHome, source.Receipt.Binding.ProviderHomeProof
		key := "CODEX_HOME"
		if spec.Executor == "claude" {
			key = "CLAUDE_CONFIG_DIR"
		}
		// Run is a dedicated process that becomes this provider; retain its original profile.
		if err := os.Setenv(key, binding.ProviderHome); err != nil {
			return s.failPersistent(dir, err)
		}
	}
	ac, err = ac.PrepareInteractive(s.Runtime)
	if err != nil {
		return s.failPersistent(dir, err)
	}
	if spec.ResumeFrom != "" && !ac.HasLifecycleHooks() {
		return s.failPersistent(dir, fmt.Errorf("SESSION_RECOVERY_HOOKS_UNAVAILABLE"))
	}
	lease, err := s.claimWorkspace(ctx, binding.Directory, spec.Key)
	if err != nil {
		return s.failWorkspaceClaim(dir, err)
	}
	defer lease()
	path, err := s.lifecycleFile(binding)
	if err != nil {
		return err
	}
	if spec.Executor == "codex" || spec.ResumeFrom != "" {
		_, scope, processes, observeErr := paneProcessSnapshot(binding.PID)
		if observeErr != nil {
			return observeErr
		}
		binding.Scope, binding.Processes = scope, processes
	}
	state := sessionLifecycle{Binding: binding, Executor: spec.Executor, Model: ac.Model, Permission: ac.Permission, Workspace: receipt.Workspace, State: "submitting", LaunchKey: spec.Key, InitialLaunch: true, Tools: map[string]bool{}, UpdatedMS: time.Now().UnixMilli()}
	state.Resuming = spec.ResumeFrom != ""
	if err = writeJSON(path, state); err != nil {
		return err
	}
	promptFile := filepath.Join(dir, "prompt.txt")
	if err = os.WriteFile(promptFile, []byte(sessionPrompt(dir, spec)), 0600); err != nil {
		return err
	}
	spawn.RecordAgentSession(s.Runtime, receipt.Session, ac)
	lease()
	// The TUI owns the pane and remains alive after each completion callback.
	command := ac.InteractiveFromPromptFile(promptFile)
	if state.Resuming {
		command = ac.ResumeInteractiveFromPromptFile(spec.ResumeProvider, promptFile)
	}
	if err = syscall.Exec("/bin/sh", []string{"sh", "-c", command}, gitcontext.ForDirectory(os.Environ())); err != nil {
		return s.failPersistent(dir, err)
	}
	return nil
}

func (s Service) failPersistent(dir string, err error) error {
	started, stopped := false, true
	if problem := writeJSON(filepath.Join(dir, "result.json"), Result{State: "failed", Summary: err.Error(), ExitCode: -1, ExecutionStarted: &started, ExitCodeSource: "not_started", InputStopped: &stopped, OutcomeKnown: &stopped, FinishedMS: time.Now().UnixMilli()}); problem != nil {
		return problem
	}
	return err
}

func (s Service) bindInitialSession(dir string, state *sessionLifecycle, binding SessionBinding, provider string) error {
	if state.Resuming && (state.Binding.ProviderID == "" || provider != state.Binding.ProviderID) {
		return fmt.Errorf("SESSION_BINDING_CONFLICT")
	}
	binding.ProviderHome = providerHome(state.Executor)
	binding.ProviderHomeProof = sessionDirectoryProof(binding.ProviderHome)
	if state.Resuming && (binding.ProviderHome == "" || binding.ProviderHome != state.Binding.ProviderHome || binding.ProviderHomeProof != state.Binding.ProviderHomeProof) {
		return fmt.Errorf("SESSION_BINDING_CONFLICT")
	}
	snapshot, scope, scoped, err := paneProcessSnapshot(binding.PID)
	if err != nil {
		return err
	}
	if (state.Executor == "codex" || state.Resuming) && (state.Binding.resourceID() != binding.resourceID() || state.Binding.PID != binding.PID || state.Binding.Directory != binding.Directory || state.Binding.Scope != "" && state.Binding.Scope != scope || state.Binding.Processes[binding.PID] != "" && state.Binding.Processes[binding.PID] != snapshot[binding.PID].Token) {
		return fmt.Errorf("SESSION_BINDING_CONFLICT")
	}
	binding.Scope, binding.Processes, binding.ProviderID = scope, scoped, provider
	binding.ForeignProcesses = map[int]string{}
	descendants := descendantProcesses(snapshot, binding.PID)
	for pid, token := range scoped {
		if descendants[pid] == "" {
			binding.ForeignProcesses[pid] = token
		}
	}
	var receipt Receipt
	if err = readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
		return err
	}
	if receipt.Session != binding.ID || receipt.Workspace == nil || receipt.Workspace.Directory != binding.Directory {
		return fmt.Errorf("SESSION_BINDING_CONFLICT")
	}
	receipt.Binding, receipt.State = &binding, "running"
	if err = writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		return err
	}
	state.Binding, state.InitialLaunch = binding, false
	return nil
}

// CloseSession is an explicit, identity-bound user action; completion never calls it.
func (s Service) CloseSession(ctx context.Context, key string) (Status, error) {
	dir, err := s.directory(key)
	if err != nil {
		return Status{}, err
	}
	var receipt Receipt
	if err = readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
		return Status{}, err
	}
	var closed Status
	if readJSON(filepath.Join(dir, "closed.json"), &closed) == nil {
		return closed, nil
	}
	if receipt.Binding == nil {
		return Status{}, fmt.Errorf("SESSION_LIFECYCLE_UNAVAILABLE")
	}
	binding, err := s.paneBinding(receipt.Session, false)
	if err != nil {
		return Status{}, fmt.Errorf("SESSION_TARGET_NOT_FOUND")
	}
	if binding.resourceID() != receipt.Binding.resourceID() || binding.Directory != receipt.Binding.Directory {
		return Status{}, fmt.Errorf("SESSION_BINDING_CONFLICT")
	}
	path, err := s.lifecycleFile(binding)
	if err != nil {
		return Status{}, err
	}
	unlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return Status{}, err
	}
	defer unlock()
	var state sessionLifecycle
	if readJSON(path, &state) != nil || state.Binding.ProviderID != receipt.Binding.ProviderID {
		return Status{}, fmt.Errorf("SESSION_BINDING_CONFLICT")
	}
	if state.State != "idle" || state.LaunchKey != "" || len(state.Tools) != 0 {
		return Status{}, fmt.Errorf("SESSION_NOT_IDLE")
	}
	if !sessionProcessesStopped(*receipt.Binding) {
		return Status{}, fmt.Errorf("SESSION_NOT_IDLE")
	}
	meta := sessmeta.New(s.Runtime.HomeDir)
	meta.DataDir = s.Runtime.DataDir
	if err = os.MkdirAll(filepath.Join(s.Runtime.DataDir, "agents", "closed-sessions"), 0700); err != nil {
		return Status{}, err
	}
	if err = application.NewSessions(s.Runtime, meta, nil).Kill(ctx, binding.ID, false); err != nil {
		return Status{}, err
	}
	closed = Status{Receipt: receipt}
	closed.State = "closed"
	if err = writeJSON(filepath.Join(s.Runtime.DataDir, "agents", "closed-sessions", binding.resourceID()+".json"), closed); err != nil {
		return Status{}, err
	}
	if err = writeJSON(filepath.Join(dir, "closed.json"), closed); err != nil {
		return Status{}, err
	}
	return closed, nil
}
