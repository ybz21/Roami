package agentexecution

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/ybz21/Roami/backend/project"
	"github.com/ybz21/Roami/backend/worktree"
	"github.com/ybz21/Roami/internal/metadb"
	core "github.com/ybz21/Roami/internal/storage"
)

type Workspace struct {
	ProjectID string `json:"projectId,omitempty"`
	Directory string `json:"directory"`
	Branch    string `json:"branch,omitempty"`
	Base      string `json:"base,omitempty"`
	StartOID  string `json:"startOid,omitempty"`
}

func (s Service) platform(ctx context.Context) (*metadb.DB, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	database, err := core.Open(s.Runtime.HomeDir, core.Options{HomeDir: s.Runtime.HomeDir, DataDir: s.Runtime.DataDir})
	if err != nil {
		return nil, err
	}
	return metadb.NewLocal(database), nil
}

// prepareWorkspace reads project identity through its store; only Go's worktree service mutates Git.
func (s Service) prepareWorkspace(ctx context.Context, spec Spec, launchHash string) (Workspace, error) {
	if spec.ProjectID == "" {
		if !filepath.IsAbs(spec.Directory) {
			return Workspace{}, fmt.Errorf("INVALID_EXECUTION_DIRECTORY")
		}
		info, err := os.Stat(spec.Directory)
		if err != nil {
			return Workspace{}, err
		}
		if !info.IsDir() {
			return Workspace{}, fmt.Errorf("INVALID_EXECUTION_DIRECTORY")
		}
		return Workspace{Directory: spec.Directory}, nil
	}
	db, err := s.platform(ctx)
	if err != nil {
		return Workspace{}, err
	}
	store := project.NewStore(s.Runtime.DataDir, db)
	entry, ok := store.Entry(spec.ProjectID)
	if !ok {
		return Workspace{}, fmt.Errorf("UNKNOWN_PROJECT")
	}
	directory := entry.Dir
	info, err := os.Stat(directory)
	if err != nil {
		return Workspace{}, err
	}
	if !info.IsDir() {
		return Workspace{}, fmt.Errorf("INVALID_PROJECT_DIRECTORY")
	}
	wt := worktree.New(s.Runtime.DataDir, db)
	if _, err = wt.ResolveRepo(ctx, directory); err != nil {
		if problem, ok := err.(*worktree.Err); ok && problem.Code == "NOT_GIT_REPO" {
			if spec.Base != "" || spec.Remote != "" {
				return Workspace{}, fmt.Errorf("PROJECT_HAS_NO_GIT")
			}
			return Workspace{ProjectID: entry.ID, Directory: directory}, nil
		}
		return Workspace{}, err
	}
	base := spec.Base
	if base == "" {
		base = entry.DefaultBase
	}
	created, err := wt.Create(ctx, worktree.CreateReq{
		Dir: directory, Branch: "agent/" + launchHash[:24], Base: base, Remote: spec.Remote, Dirname: "agent-" + launchHash[:24],
	})
	if err != nil {
		return Workspace{}, err
	}
	return Workspace{ProjectID: entry.ID, Directory: created.Path, Branch: created.Branch, Base: created.Base, StartOID: created.StartOid}, nil
}

func (s Service) bindWorkspace(ctx context.Context, session string, workspace Workspace) {
	if db, err := s.platform(ctx); err == nil {
		worktree.New(s.Runtime.DataDir, db).BindSessionHome(session, workspace.Directory)
	}
}

func preparationCode(err error) string {
	if problem, ok := err.(*worktree.Err); ok {
		return problem.Code
	}
	switch err.Error() {
	case "UNKNOWN_PROJECT", "PROJECT_CATALOG_UNAVAILABLE", "PROJECT_HAS_NO_GIT", "INVALID_PROJECT_DIRECTORY":
		return err.Error()
	}
	return "WORKSPACE_PREPARATION_FAILED"
}
