package agentexecution

import (
	"context"
	"fmt"
	"io"
	"path/filepath"
	"time"

	sessmeta "github.com/ybz21/Roami/internal/sessionstore"
)

// A resident controller owns the pane; each native JSON turn resumes its exact provider session.
func (s Service) runStructuredSession(ctx context.Context, dir string, initial Spec, stdout, stderr io.Writer) error {
	var receipt Receipt
	if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
		return err
	}
	if receipt.Workspace == nil || receipt.Session == "" {
		return s.failPersistent(dir, fmt.Errorf("SESSION_WORKSPACE_REQUIRED"))
	}
	binding, err := s.paneBinding(receipt.Session, false)
	if err != nil {
		return err
	}
	path, err := s.lifecycleFile(binding)
	if err != nil {
		return err
	}
	state := sessionLifecycle{Structured: true, Model: initial.Model, Permission: initial.Permission, Binding: binding, Executor: initial.Executor, State: "submitting", LaunchKey: initial.Key, Tools: map[string]bool{}, UpdatedMS: time.Now().UnixMilli()}
	if err = s.bindInitialSession(dir, &state, binding, ""); err != nil {
		return err
	}
	unlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return err
	}
	err = writeJSON(path, state)
	unlock()
	if err != nil {
		return err
	}
	fmt.Fprintln(stdout, "Roami: managed task session. Continue using the task conversation.")
	current := initial.Key
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	for {
		if current != "" {
			if err = s.structuredTurn(ctx, path, current, current == initial.Key, stdout, stderr); err != nil {
				return err
			}
			fmt.Fprintln(stdout, "\nRoami: turn finished; continue from the task conversation.")
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
		}
		var next sessionLifecycle
		if err = readJSON(path, &next); err != nil {
			return err
		}
		current = ""
		if next.State == "submitting" && next.LaunchKey != "" {
			current = next.LaunchKey
		}
	}
}

func (s Service) structuredTurn(ctx context.Context, path, key string, initial bool, stdout, stderr io.Writer) error {
	dir, err := s.directory(key)
	if err != nil {
		return err
	}
	unlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return err
	}
	var state sessionLifecycle
	var spec Spec
	var receipt Receipt
	if readJSON(path, &state) != nil || !state.Structured || state.State != "submitting" || state.LaunchKey != key || readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || spec.Executor != state.Executor || readJSON(filepath.Join(dir, "receipt.json"), &receipt) != nil {
		unlock()
		return fmt.Errorf("SESSION_BINDING_CONFLICT")
	}
	if !initial {
		if err = markStructuredStarted(dir); err != nil {
			unlock()
			return err
		}
	}
	state.State = "busy"
	state.UpdatedMS = time.Now().UnixMilli()
	err = writeJSON(path, state)
	unlock()
	if err != nil {
		return err
	}
	var lease func()
	if initial {
		lease, err = s.claimWorkspace(ctx, state.Binding.Directory, key)
	} else {
		// The submitting request reserved this writer fence before publishing its mailbox entry.
		var root string
		root, lease, err = s.lockWorkspaceWriter(ctx, state.Binding.Directory)
		if err == nil {
			var writer struct {
				Key string `json:"key"`
			}
			if readJSON(filepath.Join(root, "writer.json"), &writer) != nil || writer.Key != key {
				lease()
				return fmt.Errorf("WORKSPACE_OUTCOME_UNKNOWN")
			}
		}
	}
	if err != nil {
		return s.failPersistent(dir, err)
	}
	defer lease()
	spec.Model, spec.Permission = state.Model, state.Permission
	result, provider := s.structuredProcess(ctx, dir, spec, receipt, state.Binding.ProviderID, stdout, stderr)
	// Completion includes an exit and absence of writers outside the original pane baseline.
	stopped := false
	for i := 0; i < 20; i++ {
		if sessionProcessesStopped(state.Binding) {
			stopped = true
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	unlock, err = lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return err
	}
	defer unlock()
	var latest sessionLifecycle
	if readJSON(path, &latest) != nil || latest.LaunchKey != key || latest.Binding.resourceID() != state.Binding.resourceID() || latest.Binding.ProviderID != state.Binding.ProviderID {
		return fmt.Errorf("SESSION_BINDING_CONFLICT")
	}
	if !stopped {
		latest.State = "unknown"
		latest.UpdatedMS = time.Now().UnixMilli()
		if err = writeJSON(path, latest); err != nil {
			return err
		}
		return fmt.Errorf("SESSION_PROCESS_STOP_UNCONFIRMED")
	}
	if provider != "" {
		latest.Binding.ProviderID = provider
	}
	receipt.Binding = &latest.Binding
	if err = writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		return err
	}
	result.InputStopped = &stopped
	if err = writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
		return err
	}
	latest.State, latest.LaunchKey = "idle", ""
	latest.UpdatedMS = time.Now().UnixMilli()
	if err = writeJSON(path, latest); err != nil {
		return err
	}
	meta := sessmeta.New(s.Runtime.HomeDir)
	meta.DataDir = s.Runtime.DataDir
	if provider != "" {
		_ = meta.SetAgentSession(latest.Binding.Name, provider)
	}
	return nil
}
