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

// BranchCreatedForTask requires matching branch-birth and checkout reflog records.
func BranchCreatedForTask(ctx context.Context, directory, previous, current, startOID string) bool {
	if previous == "" || current == "" || startOID == "" {
		return false
	}
	if _, err := git(ctx, directory, "merge-base", "--is-ancestor", startOID, "refs/heads/"+current); err != nil {
		return false
	}
	read := func(ref string) (string, error) {
		return git(ctx, directory, "reflog", "show", "--max-count=256", "--date=raw", "--format=%H%x09%gD%x09%gs", ref)
	}
	branchLog, err := read("refs/heads/" + current)
	if err != nil {
		return false
	}
	birth := ""
	for _, line := range strings.Split(branchLog, "\n") {
		fields := strings.SplitN(line, "\t", 3)
		if len(fields) == 3 && strings.HasPrefix(fields[2], "branch: Created from ") {
			_, date, ok := strings.Cut(fields[1], "@{")
			if ok {
				birth = fields[0] + "\t" + date
			}
		}
	}
	if birth == "" {
		return false
	}
	headLog, err := read("HEAD")
	if err != nil {
		return false
	}
	for _, line := range strings.Split(headLog, "\n") {
		fields := strings.SplitN(line, "\t", 3)
		if len(fields) == 3 && fields[2] == "checkout: moving from "+previous+" to "+current {
			_, date, ok := strings.Cut(fields[1], "@{")
			if ok && fields[0]+"\t"+date == birth {
				return true
			}
		}
	}
	return false
}
