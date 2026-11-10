package agentexecution

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"

	"github.com/ybz21/Roami/internal/memguard"
)

func (s Service) sessionExecutionMissing(binding SessionBinding) bool {
	if binding.Name == "" || binding.PID <= 0 || binding.Processes[binding.PID] == "" || binding.HostProof != "" && binding.HostProof != sessionHostProof() {
		return false
	}
	identity, err := s.Runtime.SessionIdentity(binding.Name)
	if err != nil || identity != "" {
		return false
	}
	pids, err := memguard.RecordedScopeProcesses(binding.Scope)
	if err != nil || len(pids) != 0 {
		return false
	}
	processes, err := processSnapshot()
	if err != nil {
		return false
	}
	for pid, token := range binding.Processes {
		if pid <= 0 || token == "" || processes[pid].Token == token {
			return false
		}
	}
	identity, err = s.Runtime.SessionIdentity(binding.Name)
	if err != nil || identity != "" {
		return false
	}
	pids, err = memguard.RecordedScopeProcesses(binding.Scope)
	return err == nil && len(pids) == 0
}

func (s Service) missingSessionStatus(key string, status Status, original Receipt) (Status, error) {
	if !s.sessionExecutionMissing(*status.Binding) {
		return status, nil
	}
	dir, err := s.directory(key)
	if err != nil {
		return status, err
	}
	var latest Receipt
	if readJSON(filepath.Join(dir, "receipt.json"), &latest) != nil || !reflect.DeepEqual(latest, original) {
		return status, nil
	}
	var completed Result
	if err := readJSON(filepath.Join(dir, "result.json"), &completed); err == nil {
		status.State, status.Result = completed.State, &completed
		return status, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return status, err
	}
	// Retire local admission only; missing execution never proves stopped input or effects.
	unconfirmed := false
	status.ObservationErrorCode = "SESSION_EXECUTION_MISSING"
	status.Result = &Result{State: "failed", ErrorCode: status.ObservationErrorCode, Summary: status.ObservationErrorCode, ExitCode: -1, InputStopped: &unconfirmed, OutcomeKnown: &unconfirmed}
	return status, nil
}
