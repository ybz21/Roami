package worktree

import "context"

// ClosePreflight reuses proven local merge evidence; unknown branches fetch only their base.
func (s *Service) ClosePreflight(ctx context.Context, path string) (Worktree, error) {
	w, err := s.inspectCloseWorktree(ctx, path)
	if err != nil || w.MergedInto != "" || w.Base == "" || w.Head == w.StartOid {
		return w, err
	}
	if _, err := git(ctx, path, "remote", "get-url", "origin"); err != nil {
		return w, nil
	}
	nctx, cancel := context.WithTimeout(ctx, syncTimeout)
	defer cancel()
	// No branch enumeration or sibling worktree inspection is needed to verify this base.
	_, _ = git(nctx, path, "fetch", "--no-tags", "origin", "+refs/heads/"+w.Base+":refs/remotes/origin/"+w.Base)
	if repo, err := s.ResolveRepo(ctx, path); err == nil {
		s.invalidate(repo)
	}
	return s.inspectCloseWorktree(ctx, path)
}

func (s *Service) inspectCloseWorktree(ctx context.Context, path string) (Worktree, error) {
	w, err := s.LifecycleDetails(ctx, path)
	if err != nil {
		return w, err
	}
	s.enrichWorktree(ctx, &w, remoteState{})
	return w, nil
}
