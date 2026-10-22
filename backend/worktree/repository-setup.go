package worktree

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
)

type RepositoryState struct {
	Repo       bool   `json:"repo"`
	HasCommits bool   `json:"hasCommits"`
	Root       string `json:"root,omitempty"`
}

func (s *Service) RepositoryState(ctx context.Context, dir string) (RepositoryState, error) {
	if !filepath.IsAbs(dir) {
		return RepositoryState{}, errf("BAD_PATH", "directory must be absolute")
	}
	info, err := os.Stat(dir)
	if err != nil || !info.IsDir() {
		return RepositoryState{}, errf("BAD_PATH", "directory does not exist")
	}
	out, err := git(ctx, dir, "rev-parse", "--is-inside-work-tree")
	if err != nil {
		if strings.Contains(out, "not a git repository") {
			if _, statErr := os.Lstat(filepath.Join(dir, ".git")); os.IsNotExist(statErr) {
				return RepositoryState{}, nil
			}
		}
		return RepositoryState{}, errf("GIT_PROBE_FAILED", "%s", out)
	}
	if out != "true" {
		return RepositoryState{}, errf("BAD_PATH", "directory must be a working tree")
	}
	root, err := WorktreeRoot(ctx, dir)
	if err != nil {
		return RepositoryState{}, err
	}
	_, err = git(ctx, root, "rev-parse", "--verify", "HEAD^{commit}")
	if err != nil {
		// Only an unborn branch is repairable; a damaged HEAD needs manual recovery.
		ref, refErr := git(ctx, root, "symbolic-ref", "-q", "HEAD")
		if refErr != nil || !strings.HasPrefix(ref, "refs/heads/") {
			return RepositoryState{}, errf("GIT_PROBE_FAILED", "cannot resolve HEAD")
		}
		_, refErr = git(ctx, root, "show-ref", "--quiet", "--verify", ref)
		var exitErr *exec.ExitError
		if !errors.As(refErr, &exitErr) || exitErr.ExitCode() != 1 {
			return RepositoryState{}, errf("GIT_PROBE_FAILED", "cannot read HEAD commit")
		}
	}
	return RepositoryState{Repo: true, HasCommits: err == nil, Root: root}, nil
}

// InitializeRepository snapshots project files so the first worktree contains the project.
func (s *Service) InitializeRepository(ctx context.Context, dir string) (RepositoryState, error) {
	state, err := s.RepositoryState(ctx, dir)
	if err != nil {
		return RepositoryState{}, err
	}
	dir = canonical(dir)
	if state.Repo && state.Root != dir {
		return RepositoryState{}, errf("INIT_ROOT_REQUIRED", "initialize at repository root: %s", state.Root)
	}
	// A directory lock also serializes requests before .git exists, without adding a project file.
	f, err := os.Open(dir)
	if err != nil {
		return RepositoryState{}, errf("BAD_PATH", "%v", err)
	}
	defer f.Close()
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return RepositoryState{}, errf("LOCK_FAILED", "%v", err)
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	state, err = s.RepositoryState(ctx, dir)
	if err != nil {
		return RepositoryState{}, err
	}
	if state.Repo && state.Root != dir {
		return RepositoryState{}, errf("INIT_ROOT_REQUIRED", "initialize at repository root: %s", state.Root)
	}
	if !state.Repo {
		if out, err := git(ctx, dir, "init", "-b", "main"); err != nil {
			return RepositoryState{}, errf("GIT_INIT_FAILED", "%s", out)
		}
	}
	repo, err := s.ResolveRepo(ctx, dir)
	if err != nil {
		return RepositoryState{}, err
	}
	unlock, err := s.lock(repo)
	if err != nil {
		return RepositoryState{}, err
	}
	defer unlock()
	defer s.invalidate(repo)
	state, err = s.RepositoryState(ctx, dir)
	if err != nil || state.HasCommits {
		return state, err
	}
	if out, err := git(ctx, dir, "add", "--all", "--", "."); err != nil {
		return RepositoryState{}, errf("GIT_INIT_FAILED", "%s", out)
	}
	if out, err := gitID(ctx, dir, "commit", "--allow-empty", "-m", "chore: initial project snapshot"); err != nil {
		return RepositoryState{}, errf("GIT_INIT_FAILED", "%s", out)
	}
	return s.RepositoryState(ctx, dir)
}
