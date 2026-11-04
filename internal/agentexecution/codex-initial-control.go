package agentexecution

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
)

func (s Service) cancelInitialCodex(key string, status Status) (Status, bool, error) {
	dir, _ := s.directory(key)
	var spec Spec
	if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || !spec.Persistent || spec.Executor != "codex" || spec.SessionID != "" || spec.Key != key {
		return status, false, nil
	}
	unlock, err := lock(filepath.Join(dir, "initial-control.lock"))
	if err != nil {
		return status, true, err
	}
	defer unlock()
	var current Spec
	var receipt Receipt
	if readJSON(filepath.Join(dir, "spec.json"), &current) != nil || current != spec || readJSON(filepath.Join(dir, "receipt.json"), &receipt) != nil || receipt.Session != status.Session || !reflect.DeepEqual(receipt.Workspace, status.Workspace) {
		return status, true, fmt.Errorf("SESSION_BINDING_CONFLICT")
	}
	status.Receipt = receipt
	var result Result
	if err = readJSON(filepath.Join(dir, "result.json"), &result); err == nil {
		status.State, status.Result = result.State, &result
		return status, true, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return status, true, err
	}
	if receipt.Binding != nil {
		// Do not reenter Status while holding the initial control lock.
		current, err := s.sessionExecutionStatus(key, status)
		if err != nil || current.Result != nil {
			return current, true, err
		}
		current, err = s.cancelSession(key, current)
		return current, true, err
	}
	if err = writeJSON(filepath.Join(dir, "cancel.json"), map[string]bool{"cancel": true}); err != nil {
		return status, true, err
	}
	status.State = "cancelling"
	return status, true, nil
}
