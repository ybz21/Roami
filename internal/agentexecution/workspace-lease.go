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

// A lost runner's lease remains quarantined until its durable outcome is known.
func (s Service) claimWorkspace(ctx context.Context, directory, launchKey string) (func(), error) {
	canonical, err := canonicalWorkspace(directory)
	if err != nil {
		return nil, err
	}
	resolveCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	checkout, resolveErr := worktree.WorktreeRoot(resolveCtx, canonical)
	resolveFailure := resolveCtx.Err()
	cancel()
	if resolveFailure != nil && resolveErr != nil {
		return nil, resolveErr
	}
	if resolveErr == nil {
		canonical = checkout
	} else if problem, ok := resolveErr.(*worktree.Err); !ok || problem.Code != "NOT_GIT_REPO" {
		return nil, resolveErr
	}
	root := filepath.Join(s.Runtime.DataDir, "agents", "workspace-leases", workspaceHash(canonical))
	if err = os.MkdirAll(root, 0700); err != nil {
		return nil, err
	}
	file, err := os.OpenFile(filepath.Join(root, "writer.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		file.Close()
		if errors.Is(err, syscall.EWOULDBLOCK) {
			return nil, fmt.Errorf("WORKSPACE_BUSY")
		}
		return nil, err
	}
	release := func() { _ = syscall.Flock(int(file.Fd()), syscall.LOCK_UN); _ = file.Close() }
	var previous struct {
		Key string `json:"key"`
	}
	if err = readJSON(filepath.Join(root, "writer.json"), &previous); err == nil {
		priorDir, e := s.directory(previous.Key)
		var result Result
		if e != nil || readJSON(filepath.Join(priorDir, "result.json"), &result) != nil || (result.State != "succeeded" && result.State != "failed" && result.State != "cancelled") {
			release()
			return nil, fmt.Errorf("WORKSPACE_OUTCOME_UNKNOWN")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
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

func workspaceLeaseCode(err error) string {
	switch err.Error() {
	case "WORKSPACE_BUSY", "WORKSPACE_OUTCOME_UNKNOWN":
		return err.Error()
	}
	return "WORKSPACE_LEASE_FAILED"
}
