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
	ac, err = ac.PrepareInteractive(s.Runtime)
	if err != nil {
		return s.failPersistent(dir, err)
	}
	lease, err := s.claimWorkspace(ctx, binding.Directory, spec.Key)
	if err != nil {
		return s.failPersistent(dir, err)
	}
	defer lease()
	path, err := s.lifecycleFile(binding)
	if err != nil {
		return err
	}
	state := sessionLifecycle{Binding: binding, Executor: spec.Executor, State: "submitting", LaunchKey: spec.Key, InitialLaunch: true, Tools: map[string]bool{}, UpdatedMS: time.Now().UnixMilli()}
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
	if err = syscall.Exec("/bin/sh", []string{"sh", "-c", ac.InteractiveFromPromptFile(promptFile)}, gitcontext.ForDirectory(os.Environ())); err != nil {
		return s.failPersistent(dir, err)
	}
	return nil
}

func (s Service) failPersistent(dir string, err error) error {
	if problem := writeJSON(filepath.Join(dir, "result.json"), Result{State: "failed", Summary: err.Error(), ExitCode: -1, FinishedMS: time.Now().UnixMilli()}); problem != nil {
		return problem
	}
	return err
}

func (s Service) bindInitialSession(dir string, state *sessionLifecycle, binding SessionBinding, provider string) error {
	snapshot, scope, scoped, err := paneProcessSnapshot(binding.PID)
	if err != nil {
		return err
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
	if err = application.NewSessions(s.Runtime, meta, nil).Kill(ctx, binding.ID, false); err != nil {
		return Status{}, err
	}
	closed = Status{Receipt: receipt}
	closed.State = "closed"
	if err = writeJSON(filepath.Join(dir, "closed.json"), closed); err != nil {
		return Status{}, err
	}
	return closed, nil
}
