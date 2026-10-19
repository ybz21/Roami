package worktree

import (
	"context"
	"os/exec"
	"strings"
)

// BranchWasRenamed preserves task identity after a semantic rename, never a checkout switch.
func BranchWasRenamed(ctx context.Context, directory, previous, current, startOID string) bool {
	if previous == "" || startOID == "" {
		return false
	}
	_, err := git(ctx, directory, "show-ref", "--verify", "--quiet", "refs/heads/"+previous)
	exit, ok := err.(*exec.ExitError)
	if !ok || exit.ExitCode() != 1 {
		return false
	}
	_, err = git(ctx, directory, "merge-base", "--is-ancestor", startOID, "refs/heads/"+current)
	if err != nil {
		return false
	}
	log, err := git(ctx, directory, "reflog", "show", "--max-count=256", "--format=%gs", "refs/heads/"+current)
	if err != nil {
		return false
	}
	for _, line := range strings.Split(log, "\n") {
		rename, ok := strings.CutPrefix(line, "Branch: renamed refs/heads/")
		if !ok {
			continue
		}
		from, to, ok := strings.Cut(rename, " to refs/heads/")
		if ok && to == current {
			if from == previous {
				return true
			}
			current = from
		}
	}
	return false
}
