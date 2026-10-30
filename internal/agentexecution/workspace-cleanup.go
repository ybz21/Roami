package agentexecution

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/ybz21/Roami/backend/worktree"
)

// CleanupWorkspace removes only a worktree created by this launch, after stop proof.
func (s Service) CleanupWorkspace(ctx context.Context, key string) (map[string]string, error) {
	dir, err := s.directory(key)
	if err != nil {
		return nil, err
	}
	unlock, err := lock(filepath.Join(dir, "cleanup.lock"))
	if err != nil {
		return nil, err
	}
	defer unlock()
	var prior map[string]string
	if readJSON(filepath.Join(dir, "cleaned.json"), &prior) == nil {
		return prior, nil
	}
	var spec Spec
	var receipt Receipt
	if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || spec.Key != key || readJSON(filepath.Join(dir, "receipt.json"), &receipt) != nil {
		return nil, fmt.Errorf("WORKSPACE_CLEANUP_UNAVAILABLE")
	}
	result := map[string]string{"state": "cleaned"}
	workspace := receipt.Workspace
	if workspace == nil || spec.ProjectID == "" || spec.WorkspaceID != "" || workspace.Branch == "" || workspace.Base == "" {
		return result, nil
	}
	if spec.Executor == "native" {
		var stopped Result
		if readJSON(filepath.Join(dir, "result.json"), &stopped) != nil || stopped.Summary != "NATIVE_TOOLS_STOPPED" {
			return nil, fmt.Errorf("WORKSPACE_OUTCOME_UNKNOWN")
		}
	} else {
		var closed Status
		if receipt.Binding == nil || readJSON(filepath.Join(s.Runtime.DataDir, "agents", "closed-sessions", receipt.Binding.resourceID()+".json"), &closed) != nil || closed.State != "closed" || closed.Session != receipt.Session || closed.Binding == nil || closed.Binding.ProviderID != receipt.Binding.ProviderID {
			return nil, fmt.Errorf("SESSION_NOT_IDLE")
		}
	}
	db, err := s.platform(ctx)
	if err != nil {
		return nil, err
	}
	wt := worktree.New(s.Runtime.DataDir, db)
	finish := func() (map[string]string, error) {
		if err := os.Remove(filepath.Join(s.Runtime.DataDir, "agents", "workspaces", workspace.ID+".json")); err != nil && !os.IsNotExist(err) {
			return nil, err
		}
		if err := writeJSON(filepath.Join(dir, "cleaned.json"), result); err != nil {
			return nil, err
		}
		return result, nil
	}
	// A removed worktree is safe to replay after a crash before writing the receipt.
	if _, err := os.Stat(workspace.Directory); os.IsNotExist(err) {
		return finish()
	}
	release, err := s.claimWorkspace(ctx, workspace.Directory, key)
	if err != nil {
		return nil, err
	}
	defer release()
	current, err := s.reuseWorkspace(ctx, Spec{ProjectID: spec.ProjectID, WorkspaceID: workspace.ID})
	if err != nil {
		return nil, err
	}
	entries, err := wt.List(ctx, current.Directory)
	if err != nil {
		return nil, err
	}
	for _, entry := range entries {
		if entry.Path != current.Directory {
			continue
		}
		if entry.IsMain || entry.External {
			return nil, fmt.Errorf("WORKSPACE_CLEANUP_UNAVAILABLE")
		}
		if len(entry.Sessions) != 0 {
			return nil, fmt.Errorf("WORKSPACE_BUSY")
		}
		deleteBranch := !entry.Adopted && (entry.Head == workspace.StartOID || entry.MergedInto != "")
		if err = wt.Remove(ctx, worktree.RemoveReq{Path: current.Directory, DeleteBranch: deleteBranch, ForceDeleteBranch: deleteBranch}); err != nil {
			if problem, ok := err.(*worktree.Err); ok {
				return nil, fmt.Errorf("%s", problem.Code)
			}
			return nil, err
		}
		return finish()
	}
	return nil, fmt.Errorf("WORKSPACE_STALE")
}
