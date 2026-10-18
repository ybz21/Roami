package agentexecution

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"syscall"
	"time"
)

type NativeStopConfirmation struct {
	Stopped        bool   `json:"stopped"`
	EvidenceSHA256 string `json:"evidenceSha256"`
}

type NativeReconciliation struct {
	Released       bool   `json:"released"`
	InputStopped   bool   `json:"inputStopped"`
	LaunchKey      string `json:"launchKey"`
	WorkspaceID    string `json:"workspaceId"`
	EvidenceSHA256 string `json:"evidenceSha256"`
	Reused         bool   `json:"reused"`
}

var nativeEvidenceDigest = regexp.MustCompile(`^[0-9a-f]{64}$`)

// ReconcileNative uses the same trusted local stop boundary as HoldNative, without replaying work.
func (s Service) ReconcileNative(ctx context.Context, key string, proof NativeStopConfirmation) (NativeReconciliation, error) {
	empty := NativeReconciliation{}
	if !proof.Stopped || !nativeEvidenceDigest.MatchString(proof.EvidenceSHA256) {
		return empty, fmt.Errorf("INVALID_NATIVE_STOP_EVIDENCE")
	}
	if err := ctx.Err(); err != nil {
		return empty, err
	}
	dir, err := s.directory(key)
	if err != nil {
		return empty, err
	}
	launchLock, err := os.OpenFile(filepath.Join(dir, "launch.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return empty, err
	}
	defer launchLock.Close()
	if err = syscall.Flock(int(launchLock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return empty, fmt.Errorf("NATIVE_RECONCILIATION_BUSY")
	}
	defer syscall.Flock(int(launchLock.Fd()), syscall.LOCK_UN)
	var spec Spec
	var receipt Receipt
	if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || spec.Key != key || spec.Executor != "native" || readJSON(filepath.Join(dir, "receipt.json"), &receipt) != nil || receipt.State != "native_running" || receipt.Workspace == nil || receipt.Workspace.ID == "" {
		return empty, fmt.Errorf("NATIVE_RECONCILIATION_BINDING_MISSING")
	}
	ack := NativeReconciliation{Released: true, InputStopped: true, LaunchKey: key, WorkspaceID: receipt.Workspace.ID, EvidenceSHA256: proof.EvidenceSHA256}
	var result Result
	hasResult := false
	if err = readJSON(filepath.Join(dir, "result.json"), &result); err == nil {
		if result.Summary != "NATIVE_TOOLS_STOPPED" && result.Summary != "NATIVE_STOP_CONFIRMED_OUTCOME_UNKNOWN" {
			return empty, fmt.Errorf("NATIVE_RECONCILIATION_RESULT_CONFLICT")
		}
		if result.State != "succeeded" && result.State != "failed" && result.State != "cancelled" {
			return empty, fmt.Errorf("NATIVE_RECONCILIATION_RESULT_CONFLICT")
		}
		if result.Summary == "NATIVE_STOP_CONFIRMED_OUTCOME_UNKNOWN" && (result.InputStopped == nil || !*result.InputStopped || result.OutcomeKnown == nil || *result.OutcomeKnown || !nativeEvidenceDigest.MatchString(result.StopEvidence)) {
			return empty, fmt.Errorf("NATIVE_RECONCILIATION_RESULT_CONFLICT")
		}
		hasResult = true
	} else if !errors.Is(err, os.ErrNotExist) {
		return empty, err
	}
	root, release, err := s.lockWorkspaceWriter(ctx, receipt.Workspace.Directory)
	if err != nil {
		if hasResult && err.Error() == "WORKSPACE_BUSY" {
			var writer struct {
				Key string `json:"key"`
			}
			if readJSON(filepath.Join(root, "writer.json"), &writer) == nil && writer.Key != "" && writer.Key != key {
				ack.Reused = true
				return ack, nil
			}
		}
		return empty, err
	}
	defer release()
	if hasResult {
		ack.Reused = true
		return ack, nil
	}
	var writer struct {
		Key string `json:"key"`
	}
	if readJSON(filepath.Join(root, "writer.json"), &writer) != nil || writer.Key != key {
		return empty, fmt.Errorf("NATIVE_RECONCILIATION_WRITER_CHANGED")
	}
	if err := ctx.Err(); err != nil {
		return empty, err
	}
	stopped, known := true, false
	result = Result{State: "failed", Summary: "NATIVE_STOP_CONFIRMED_OUTCOME_UNKNOWN", FinishedMS: time.Now().UnixMilli(), InputStopped: &stopped, OutcomeKnown: &known, StopEvidence: proof.EvidenceSHA256}
	if err = writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
		return empty, err
	}
	return ack, nil
}
