package agentexecution

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"
)

// HoldNative prepares through Go and keeps the shared writer lease until explicit stop confirmation.
func (s Service) HoldNative(ctx context.Context, spec Spec, input *json.Decoder, output io.Writer) error {
	if spec.Executor != "native" || spec.TimeoutSeconds < 1 || spec.TimeoutSeconds > 86400 || (spec.ProjectID == "" && !filepath.IsAbs(spec.Directory)) || (spec.ProjectID != "" && spec.Directory != "") || (spec.ProjectID == "" && (spec.WorkspaceID != "" || spec.Base != "" || spec.Remote != "")) || (spec.WorkspaceID != "" && (spec.Base != "" || spec.Remote != "")) {
		return fmt.Errorf("INVALID_NATIVE_WORKSPACE_SPEC")
	}
	dir, err := s.directory(spec.Key)
	if err != nil {
		return err
	}
	if err = os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	unlock, err := lock(filepath.Join(dir, "launch.lock"))
	if err != nil {
		return err
	}
	defer func() { unlock() }()
	if _, err = os.Stat(filepath.Join(dir, "spec.json")); !os.IsNotExist(err) {
		return fmt.Errorf("NATIVE_WORKSPACE_ALREADY_USED")
	}
	if err = writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
		return err
	}
	deadline := time.Now().Add(time.Duration(spec.TimeoutSeconds) * time.Second)
	ctx, cancel := context.WithDeadline(ctx, deadline)
	defer cancel()
	receipt := Receipt{State: "preparing", DeadlineMS: deadline.UnixMilli()}
	if err = writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		return err
	}
	prepareCtx, prepareCancel := context.WithTimeout(ctx, 120*time.Second)
	workspace, err := s.prepareWorkspace(prepareCtx, spec, filepath.Base(dir))
	prepareCancel()
	if err != nil {
		return err
	}
	lease, err := s.claimWorkspace(ctx, workspace.Directory, spec.Key)
	if err != nil {
		return err
	}
	defer lease()
	if err = os.WriteFile(filepath.Join(dir, "started"), nil, 0600); err != nil {
		return err
	}
	receipt.Workspace, receipt.State = &workspace, "native_running"
	if err = writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		return err
	}
	unlock()
	unlock = func() {}
	encoder := json.NewEncoder(output)
	if err = encoder.Encode(receipt); err != nil {
		return err
	}
	type confirmation struct {
		State   string `json:"state"`
		Stopped bool   `json:"stopped"`
	}
	type received struct {
		frame confirmation
		err   error
	}
	finished := make(chan received, 1)
	go func() { var frame confirmation; err := input.Decode(&frame); finished <- received{frame, err} }()
	select {
	case <-ctx.Done():
		return fmt.Errorf("NATIVE_WORKSPACE_OUTCOME_UNKNOWN")
	case value := <-finished:
		if value.err != nil || !value.frame.Stopped || (value.frame.State != "succeeded" && value.frame.State != "failed" && value.frame.State != "cancelled") {
			return fmt.Errorf("NATIVE_WORKSPACE_OUTCOME_UNKNOWN")
		}
		result := Result{State: value.frame.State, Summary: "NATIVE_TOOLS_STOPPED", FinishedMS: time.Now().UnixMilli()}
		if err = writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
			return err
		}
		return encoder.Encode(map[string]bool{"released": true})
	}
}
