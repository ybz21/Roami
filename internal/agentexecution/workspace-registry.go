package agentexecution

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"

	"github.com/ybz21/Roami/backend/project"
	"github.com/ybz21/Roami/backend/worktree"
)

func canonicalWorkspace(directory string) (string, error) {
	if !filepath.IsAbs(directory) {
		return "", fmt.Errorf("INVALID_EXECUTION_DIRECTORY")
	}
	canonical, err := filepath.EvalSymlinks(directory)
	if err != nil {
		return "", err
	}
	info, err := os.Stat(canonical)
	if err != nil {
		return "", err
	}
	if !info.IsDir() {
		return "", fmt.Errorf("INVALID_EXECUTION_DIRECTORY")
	}
	return filepath.Clean(canonical), nil
}

func workspaceHash(value string) string {
	hash := sha256.Sum256([]byte(value))
	return hex.EncodeToString(hash[:])
}

func (s Service) rememberWorkspace(workspace Workspace) (Workspace, error) {
	directory, err := canonicalWorkspace(workspace.Directory)
	if err != nil {
		return Workspace{}, err
	}
	workspace.Directory = directory
	workspace.ID = workspaceHash(workspace.ProjectID + "\x00" + directory)
	registry := filepath.Join(s.Runtime.DataDir, "agents", "workspaces")
	if err = os.MkdirAll(registry, 0700); err != nil {
		return Workspace{}, err
	}
	if err = writeJSON(filepath.Join(registry, workspace.ID+".json"), workspace); err != nil {
		return Workspace{}, err
	}
	return workspace, nil
}

// Reuse never fetches, checks out, cleans or resets the user's current workspace.
func (s Service) reuseWorkspace(ctx context.Context, spec Spec) (Workspace, error) {
	if spec.ProjectID == "" || spec.Directory != "" || spec.Base != "" || spec.Remote != "" {
		return Workspace{}, fmt.Errorf("INVALID_WORKSPACE_TARGET")
	}
	decoded, err := hex.DecodeString(spec.WorkspaceID)
	if err != nil || len(decoded) != 32 || hex.EncodeToString(decoded) != spec.WorkspaceID {
		return Workspace{}, fmt.Errorf("UNKNOWN_WORKSPACE")
	}
	var workspace Workspace
	if err = readJSON(filepath.Join(s.Runtime.DataDir, "agents", "workspaces", spec.WorkspaceID+".json"), &workspace); err != nil {
		return Workspace{}, fmt.Errorf("UNKNOWN_WORKSPACE")
	}
	db, err := s.platform(ctx)
	if err != nil {
		return Workspace{}, err
	}
	entry, ok := project.NewStore(s.Runtime.DataDir, db).Entry(spec.ProjectID)
	if !ok {
		return Workspace{}, fmt.Errorf("UNKNOWN_PROJECT")
	}
	if workspace.ProjectID != entry.ID || workspace.ID != spec.WorkspaceID {
		return Workspace{}, fmt.Errorf("WORKSPACE_PROJECT_MISMATCH")
	}
	directory, err := canonicalWorkspace(workspace.Directory)
	if err != nil || directory != workspace.Directory || workspaceHash(workspace.ProjectID+"\x00"+directory) != workspace.ID {
		return Workspace{}, fmt.Errorf("WORKSPACE_STALE")
	}
	wt := worktree.New(s.Runtime.DataDir, db)
	repo, err := wt.ResolveRepo(ctx, entry.Dir)
	if err != nil {
		if problem, ok := err.(*worktree.Err); ok && problem.Code == "NOT_GIT_REPO" && workspace.Branch == "" {
			projectDir, e := canonicalWorkspace(entry.Dir)
			if e == nil && directory == projectDir {
				return workspace, nil
			}
		}
		return Workspace{}, fmt.Errorf("WORKSPACE_STALE")
	}
	actual, err := wt.ResolveRepo(ctx, directory)
	if err != nil || actual.CommonDir != repo.CommonDir {
		return Workspace{}, fmt.Errorf("WORKSPACE_STALE")
	}
	entries, err := wt.List(ctx, entry.Dir)
	if err != nil {
		return Workspace{}, err
	}
	for _, candidate := range entries {
		path, err := canonicalWorkspace(candidate.Path)
		if err == nil && path == directory && candidate.Branch == workspace.Branch && !candidate.Prunable {
			return workspace, nil
		}
	}
	return Workspace{}, fmt.Errorf("WORKSPACE_STALE")
}
