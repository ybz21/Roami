package agentexecution

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"time"

	"github.com/ybz21/Roami/backend/worktree"
)

// WorkspaceClaimFailure describes the blocked new execution, not the prior writer's outcome.
type WorkspaceClaimFailure struct {
	Phase               string `json:"phase"`
	ReasonCode          string `json:"reasonCode"`
	BlockingExecutionID string `json:"blockingExecutionId,omitempty"`
	BlockingSessionID   string `json:"blockingSessionId,omitempty"`
}

type workspaceClaimError struct {
	failure WorkspaceClaimFailure
}

func (e *workspaceClaimError) Error() string { return "WORKSPACE_OUTCOME_UNKNOWN" }

func (s Service) blockedWorkspaceWriter(key, reason string) error {
	failure := WorkspaceClaimFailure{Phase: "workspace_claim", ReasonCode: reason}
	if dir, err := s.directory(key); err == nil {
		failure.BlockingExecutionID = filepath.Base(dir)
		var receipt Receipt
		if readJSON(filepath.Join(dir, "receipt.json"), &receipt) == nil {
			failure.BlockingSessionID = receipt.Session
		}
	}
	return &workspaceClaimError{failure: failure}
}

func workspaceClaimResult(err error) Result {
	started := false
	code := workspaceLeaseCode(err)
	failure := WorkspaceClaimFailure{Phase: "workspace_claim", ReasonCode: code}
	var blocked *workspaceClaimError
	if errors.As(err, &blocked) {
		failure = blocked.failure
	}
	return Result{State: "failed", Summary: failure.ReasonCode, ErrorCode: code, ExitCode: -1,
		ExecutionStarted: &started, ExitCodeSource: "not_started", Failure: &failure,
		FinishedMS: time.Now().UnixMilli()}
}

func (s Service) failWorkspaceClaim(dir string, err error) error {
	if problem := writeJSON(filepath.Join(dir, "result.json"), workspaceClaimResult(err)); problem != nil {
		return problem
	}
	return err
}

// A lost runner keeps its writer fence until stop is confirmed.
func (s Service) lockWorkspaceWriter(ctx context.Context, directory string) (string, func(), error) {
	canonical, err := canonicalWorkspace(directory)
	if err != nil {
		return "", nil, err
	}
	resolveCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	checkout, resolveErr := worktree.WorktreeRoot(resolveCtx, canonical)
	resolveFailure := resolveCtx.Err()
	cancel()
	if resolveFailure != nil && resolveErr != nil {
		return "", nil, resolveErr
	}
	if resolveErr == nil {
		canonical = checkout
	} else if problem, ok := resolveErr.(*worktree.Err); !ok || problem.Code != "NOT_GIT_REPO" {
		return "", nil, resolveErr
	}
	root := filepath.Join(s.Runtime.DataDir, "agents", "workspace-leases", workspaceHash(canonical))
	if err = os.MkdirAll(root, 0700); err != nil {
		return "", nil, err
	}
	file, err := os.OpenFile(filepath.Join(root, "writer.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return "", nil, err
	}
	if err = syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		file.Close()
		if errors.Is(err, syscall.EWOULDBLOCK) {
			return root, nil, fmt.Errorf("WORKSPACE_BUSY")
		}
		return "", nil, err
	}
	release := func() { _ = syscall.Flock(int(file.Fd()), syscall.LOCK_UN); _ = file.Close() }
	return root, release, nil
}

func (s Service) claimWorkspace(ctx context.Context, directory, launchKey string) (func(), error) {
	root, release, err := s.lockWorkspaceWriter(ctx, directory)
	if err != nil {
		return nil, err
	}

	if err := s.workspaceWriterReady(root); err != nil {
		release()
		return nil, err
	}
	if err = writeJSON(filepath.Join(root, "writer.json"), struct {
		Key string `json:"key"`
	}{launchKey}); err != nil {
		release()
		return nil, err
	}
	return release, nil
}

func (s Service) workspaceWriterReady(root string) error {
	var previous struct {
		Key string `json:"key"`
	}
	if err := readJSON(filepath.Join(root, "writer.json"), &previous); err == nil {
		priorDir, e := s.directory(previous.Key)
		var result Result
		if e != nil {
			return s.blockedWorkspaceWriter(previous.Key, "WORKSPACE_PRIOR_LAUNCH_INVALID")
		}
		if e = readJSON(filepath.Join(priorDir, "result.json"), &result); e != nil {
			reason := "WORKSPACE_PRIOR_RESULT_UNREADABLE"
			if errors.Is(e, os.ErrNotExist) {
				reason = "WORKSPACE_PRIOR_RESULT_MISSING"
			}
			return s.blockedWorkspaceWriter(previous.Key, reason)
		}
		if result.State != "succeeded" && result.State != "failed" && result.State != "cancelled" {
			return s.blockedWorkspaceWriter(previous.Key, "WORKSPACE_PRIOR_RESULT_NOT_TERMINAL")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

func workspaceLeaseCode(err error) string {
	switch err.Error() {
	case "WORKSPACE_BUSY", "WORKSPACE_OUTCOME_UNKNOWN":
		return err.Error()
	}
	return "WORKSPACE_LEASE_FAILED"
}
